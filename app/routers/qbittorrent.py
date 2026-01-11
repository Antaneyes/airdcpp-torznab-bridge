import os
import time
import requests
import re
import urllib.parse
from fastapi import APIRouter, Response, Query, Request, Form, File, UploadFile, HTTPException
from typing import Optional
from app.config import KNOWN_CATEGORIES, AIRDCPP_URL, SAVE_PATH
from app.core.locks import GLOBAL_SEARCH_LOCK
from app.core.logging import get_logger
from app.services.persistence import (
    HASH_MAP_HEX_TO_TTH, HASH_MAP_TTH_TO_HEX, 
    FINISHED_BUNDLES_CACHE, BUNDLE_MAP_ID_TO_TTH, 
    BUNDLE_MAP_ID_TO_CAT, save_hashes, db_save_bundle,
    get_hex_hash, db_get_bundle_ids_by_tth
)
from app.services.airdcpp import get_auth_headers
from app.utils.text import clean_search_pattern, normalize_text

router = APIRouter()
logger = get_logger("app.routers.qbittorrent")

@router.get("/api/v2/app/version")
@router.get("/version/api") 
async def qbit_version():
    return Response(content="v4.3.9", media_type="text/plain")

@router.get("/api/v2/app/webApiVersion")
@router.get("/api/v2/app/webapiVersion")
async def qbit_webapi_version():
    return Response(content="2.8.2", media_type="text/plain")

@router.post("/api/v2/auth/login")
@router.post("/api/v2/auth/login/")
async def qbit_login(response: Response):
    response.set_cookie(key="SID", value="fake-session-id-12345", path="/")
    return Response(content="Ok.", media_type="text/plain")

@router.get("/api/v2/app/preferences")
async def qbit_preferences():
    return {"save_path": SAVE_PATH, "listen_port": 8000}

@router.get("/api/v2/torrents/categories")
async def qbit_categories():
    return {cat: {"name": cat, "savePath": SAVE_PATH} for cat in KNOWN_CATEGORIES}

@router.get("/api/v2/torrents/properties")
async def qbit_properties(hash: str):
    return {
        "save_path": SAVE_PATH,
        "creation_date": int(time.time()),
        "piece_size": 16384,
        "is_seed": True,
        "total_size": 0
    }

@router.get("/api/v2/torrents/files")
def qbit_files(hash: str):
    headers = get_auth_headers()
    tth = HASH_MAP_HEX_TO_TTH.get(hash, hash)
    r = requests.get(f"{AIRDCPP_URL}/api/v1/queue/bundles/0/1000", headers=headers, timeout=5)
    size, name = 0, "unknown_file"
    if r.status_code == 200:
        for b in r.json():
            if BUNDLE_MAP_ID_TO_TTH.get(str(b["id"])) == tth:
                size, name = int(float(b["size"])), b["name"]
                break
    return [{"name": name, "size": size, "progress": 1.0, "priority": 1, "is_seed": True,
        "piece_range_start": 0, "piece_range_end": 1, "availability": 1.0}]

@router.post("/api/v2/torrents/delete")
async def qbit_delete(hashes: Optional[str] = Form(None), deleteFiles: Optional[bool] = Form(False)):
    target_hashes = hashes.split('|') if hashes else []
    headers = get_auth_headers()
    for h in target_hashes:
        tth = HASH_MAP_HEX_TO_TTH.get(h)
        if tth:
            bundle_ids = db_get_bundle_ids_by_tth(tth)
            if bundle_ids:
                logger.info(f"Cancelando descargas en AirDC++ para TTH {tth}: {bundle_ids}")
                for b_id in bundle_ids:
                    try: requests.post(f"{AIRDCPP_URL}/api/v1/queue/bundles/{b_id}/remove", headers=headers, timeout=2)
                    except: pass
            if tth in FINISHED_BUNDLES_CACHE:
                del FINISHED_BUNDLES_CACHE[tth]
    return Response(content="Ok.", media_type="text/plain")

def _get_qbit_info_internal(category: Optional[str] = None):
    headers = get_auth_headers()
    try:
        r = requests.get(f"{AIRDCPP_URL}/api/v1/queue/bundles/0/1000", headers=headers, timeout=5)
        bundles = r.json() if r.status_code == 200 else []
        qbit_results, reported_tths = [], set()
        req_cat = category.lower() if category else None
        needs_save = False
        
        for b in bundles:
            bundle_id = str(b["id"])
            tth = BUNDLE_MAP_ID_TO_TTH.get(bundle_id)
            if not tth: continue
            
            bundle_cat = BUNDLE_MAP_ID_TO_CAT.get(bundle_id, "radarr").lower()
            if req_cat and bundle_cat != req_cat: continue
            
            reported_tths.add(tth)
            fake_hash = get_hex_hash(tth)
            downloaded = int(float(b.get("downloaded_bytes", 0)))
            size = int(float(b["size"]))
            progress = downloaded / size if size > 0 else 0
            is_completed = b.get("status", {}).get("completed", False) or progress >= 0.999
            
            if is_completed:
                state = "uploading"
            elif progress == 0:
                state = "stalledDL"
            else:
                state = "downloading"

            # INFO COMPLETA PARA SONARR/RADARR
            res_item = {
                "hash": fake_hash,
                "name": b["name"],
                "size": size,
                "progress": progress,
                "dlspeed": int(float(b.get("speed", 0))),
                "eta": int(float(b.get("seconds_left", 864000))),
                "state": state,
                "amount_left": max(0, size - downloaded),
                "completed": int(b.get("time_finished", 0)),
                "save_path": SAVE_PATH,
                "content_path": os.path.join(SAVE_PATH, b["name"]),
                "label": bundle_cat,
                "category": bundle_cat,
                "num_seeds": 1 if is_completed else 0,
                "num_leechs": 0,
                "added_on": int(b.get("time_added", time.time())),
                "completion_on": int(b.get("time_finished", 0))
            }
            if is_completed:
                if tth not in FINISHED_BUNDLES_CACHE:
                    logger.info(f"Bundle {b['name']} marcado como completado en cache.")
                    needs_save = True
                FINISHED_BUNDLES_CACHE[tth] = res_item
            qbit_results.append(res_item)
            
        if needs_save: save_hashes()
        for t_tth, cached in FINISHED_BUNDLES_CACHE.items():
            if t_tth not in reported_tths and (not req_cat or cached.get("category") == req_cat):
                qbit_results.append(cached)
        return qbit_results
    except Exception as e: 
        logger.error(f"Error en qbit_info: {e}")
        return []

@router.get("/api/v2/torrents/info")
def qbit_info(category: Optional[str] = None):
    return _get_qbit_info_internal(category)

@router.get("/api/v2/sync/maindata")
def qbit_maindata(category: Optional[str] = None):
    torrents = {t["hash"]: t for t in _get_qbit_info_internal(category=category)}
    return {"torrents": torrents, "full_update": True, "categories": {cat: {"name": cat, "savePath": SAVE_PATH} for cat in KNOWN_CATEGORIES}}

@router.post("/api/v2/torrents/add")
def qbit_add(request: Request, urls: Optional[str] = Form(None), category: Optional[str] = Form(None)):
    headers = get_auth_headers()
    # Usar categoría enviada por el cliente, o auto-detectar
    final_category = category if category else "sonarr"
    
    with GLOBAL_SEARCH_LOCK:
        logger.info(f"--- SOLICITUD DE DESCARGA ---")
        url_list = urls.split("\n") if urls else []
        any_success = False
        for url in url_list:
            url = url.strip()
            if not url: continue
            raw_hash = url.split("tiger:")[1].split("&")[0] if "tiger:" in url else (url.split("btih:")[1].split("&")[0] if "btih:" in url else None)
            if not raw_hash: continue
            
            tth = HASH_MAP_HEX_TO_TTH.get(raw_hash, raw_hash)
            if tth == "da39a3ee5e6b4b0d3255bfef95601890afd80709": continue
            
            try:
                expected_name = urllib.parse.unquote(url.split("dn=")[1].split("&")[0]) if "dn=" in url else "Unknown"
                logger.info(f"Buscando el archivo exacto: '{expected_name}'")
                
                res = requests.post(f"{AIRDCPP_URL}/api/v1/search", json=dict(), headers=headers, timeout=10)
                instance_id = res.json()["id"]
                
                search_payload = {"query": {"pattern": expected_name}, "priority": 2}
                requests.post(f"{AIRDCPP_URL}/api/v1/search/{instance_id}/hub_search", json=search_payload, headers=headers, timeout=10)
                
                selected_result = None
                for i in range(8):
                    time.sleep(2)
                    r_res = requests.get(f"{AIRDCPP_URL}/api/v1/search/{instance_id}/results/0/500", headers=headers, timeout=5)
                    if r_res.status_code == 200:
                        results = [r for r in r_res.json() if r.get("tth") == tth]
                        if results:
                            for r in results:
                                if r["name"] == expected_name:
                                    selected_result = r
                                    break
                            if not selected_result: selected_result = results[0]
                            break
                
                if not selected_result:
                    logger.info("  - Fallback por TTH...")
                    search_payload_tth = {"query": {"pattern": tth, "file_type": "tth"}, "priority": 2}
                    requests.post(f"{AIRDCPP_URL}/api/v1/search/{instance_id}/hub_search", json=search_payload_tth, headers=headers, timeout=10)
                    for i in range(5):
                        time.sleep(2)
                        r_res = requests.get(f"{AIRDCPP_URL}/api/v1/search/{instance_id}/results/0/100", headers=headers, timeout=5)
                        if r_res.status_code == 200:
                            results = r_res.json()
                            if results:
                                selected_result = results[0]
                                break

                if selected_result:
                    logger.info(f"Archivo hallado: {selected_result['name']}")
                    dl = requests.post(f"{AIRDCPP_URL}/api/v1/search/{instance_id}/results/{selected_result['id']}/download", json={"priority": 3}, headers=headers, timeout=10)
                    if dl.status_code < 300:
                        try:
                            bundle_id = str(dl.json()["bundle_info"]["id"])
                            db_save_bundle(bundle_id, tth, final_category)
                            any_success = True
                        except: 
                            logger.error("Error al procesar respuesta de AirDC++")
                    elif dl.status_code == 400 and "already" in dl.text.lower():
                        any_success = True
                
                requests.delete(f"{AIRDCPP_URL}/api/v1/search/{instance_id}", headers=headers, timeout=5)
            except Exception as e: logger.error(f"Fallo en descarga: {e}")
        
        if any_success: return Response(content="Ok.", status_code=200, media_type="text/plain")
        else: return Response(content="Fallo.", status_code=500, media_type="text/plain")