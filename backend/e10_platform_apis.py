"""
============================================================
E10 PLATFORM APIS — Posting real a redes sociales
STATUS: REAL (requiere OAuth tokens configurados por plataforma)

Reemplaza el stub _post_to_platform_api en e10_social.py.
No modifica la estructura de e10_social — es llamado desde ahí.

Plataformas soportadas:
  instagram   REAL — Meta Graph API (requiere IG Business/Creator + token)
  facebook    REAL — Meta Graph API Pages (requiere Page Access Token)
  twitter     REAL — Twitter API v2 (requiere OAuth 2.0 Bearer Token)
  linkedin    REAL — LinkedIn UGC API (requiere OAuth 2.0 + author URN)
  tiktok      PARCIAL — TikTok Content Posting API (video only en v2)
  threads     REAL — Meta Threads API (igual que Instagram Graph)
  youtube_shorts STUB — YouTube Data API v3 requiere video upload separado

Configuración de connection doc (e10_connections):
  platform:       "instagram" | "facebook" | "twitter" | "linkedin" | ...
  tenant_id:      tenant
  access_token:   OAuth access token
  platform_user_id: IG user ID / LinkedIn URN / Twitter user ID / FB page ID
  token_type:     "Bearer" | "OAuth"
============================================================
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("e10_platform_apis")


# ══════════════════════════════════════════════════════════════════════════════
# INSTAGRAM / THREADS — Meta Graph API
# ══════════════════════════════════════════════════════════════════════════════

async def _post_instagram_graph(
    token: str,
    ig_user_id: str,
    caption: str,
    media_url: str = "",
    is_threads: bool = False,
) -> dict:
    """
    STATUS: REAL
    Publica en Instagram o Threads via Meta Graph API.
    Proceso: (1) crear media container → (2) publish.

    Requiere: IG Business Account, token con perms instagram_basic,
              instagram_content_publish, pages_read_engagement.
    media_url debe ser URL pública (HTTPS) para fotos/videos.
    """
    base = "https://graph.instagram.com" if not is_threads else "https://graph.threads.net"
    if not ig_user_id:
        return {"status": "failed", "error": "platform_user_id (IG user ID) no configurado para este tenant"}

    # Step 1: Create media container
    create_url = f"{base}/{ig_user_id}/media"
    create_params: dict = {
        "caption":      caption,
        "access_token": token,
    }
    if media_url:
        # Detect video vs image by extension
        if any(media_url.lower().endswith(ext) for ext in (".mp4", ".mov", ".avi")):
            create_params["media_type"] = "REELS"
            create_params["video_url"]  = media_url
        else:
            create_params["image_url"]  = media_url
    else:
        # Text-only not supported on IG — use caption as image carousel placeholder
        return {
            "status":  "skipped",
            "note":    "Instagram requires media_url. Text-only posts not supported.",
            "post_id": f"ig_text_only_{uuid.uuid4().hex[:8]}",
        }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(create_url, data=create_params,
                                    timeout=aiohttp.ClientTimeout(total=30)) as r:
                data = await r.json()
                if r.status not in (200, 201) or "id" not in data:
                    return {"status": "failed", "error": data.get("error", {}).get("message", str(data)),
                            "http_status": r.status}
                container_id = data["id"]

            # Step 2: Publish
            pub_url = f"{base}/{ig_user_id}/media_publish"
            async with session.post(pub_url,
                                    data={"creation_id": container_id, "access_token": token},
                                    timeout=aiohttp.ClientTimeout(total=30)) as r2:
                pub_data = await r2.json()
                if r2.status not in (200, 201) or "id" not in pub_data:
                    return {"status": "failed",
                            "error": pub_data.get("error", {}).get("message", str(pub_data)),
                            "http_status": r2.status}
                return {
                    "status":    "published",
                    "post_id":   pub_data["id"],
                    "container": container_id,
                    "platform":  "threads" if is_threads else "instagram",
                }
    except aiohttp.ClientError as exc:
        return {"status": "failed", "error": f"HTTP error: {exc}"}
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# FACEBOOK — Meta Graph API Pages
# ══════════════════════════════════════════════════════════════════════════════

async def _post_facebook(
    token: str,
    page_id: str,
    message: str,
    media_url: str = "",
) -> dict:
    """
    STATUS: REAL
    Publica en una Facebook Page via Graph API.
    Requiere: Page Access Token con perms pages_manage_posts.
    """
    if not page_id:
        return {"status": "failed", "error": "platform_user_id (FB page ID) no configurado"}

    base = "https://graph.facebook.com/v19.0"
    try:
        async with aiohttp.ClientSession() as session:
            if media_url and any(media_url.lower().endswith(e) for e in (".jpg",".jpeg",".png",".gif",".webp")):
                url    = f"{base}/{page_id}/photos"
                params = {"url": media_url, "caption": message, "access_token": token}
            else:
                url    = f"{base}/{page_id}/feed"
                params = {"message": message, "access_token": token}
                if media_url:
                    params["link"] = media_url

            async with session.post(url, data=params,
                                    timeout=aiohttp.ClientTimeout(total=30)) as r:
                data = await r.json()
                if r.status not in (200, 201) or "id" not in data:
                    return {"status": "failed",
                            "error": data.get("error", {}).get("message", str(data)),
                            "http_status": r.status}
                return {"status": "published", "post_id": data["id"], "platform": "facebook"}
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# TWITTER/X — API v2
# ══════════════════════════════════════════════════════════════════════════════

async def _post_twitter(
    token: str,
    text: str,
    media_url: str = "",
) -> dict:
    """
    STATUS: REAL (text-only) / PARCIAL (media requires v1.1 upload first)
    Publica un tweet via Twitter API v2.
    Requiere: OAuth 2.0 Bearer Token o User Context token.
    Media upload requires additional twitter OAuth 1.0a credentials.
    """
    url     = "https://api.twitter.com/2/tweets"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload: dict = {"text": text[:280]}

    # Note: media upload requires separate /1.1/media/upload endpoint with OAuth 1.0a
    # For now: text-only posting is REAL, media is PARCIAL (media_id would need separate step)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=30)) as r:
                data = await r.json()
                if r.status not in (200, 201) or "data" not in data:
                    err = data.get("errors", [{}])[0].get("message", str(data))
                    return {"status": "failed", "error": err, "http_status": r.status}
                tweet = data["data"]
                return {
                    "status":   "published",
                    "post_id":  tweet.get("id", ""),
                    "text":     tweet.get("text", ""),
                    "platform": "twitter",
                    "note":     "text-only (media upload requires OAuth 1.0a)" if media_url else None,
                }
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# LINKEDIN — UGC API
# ══════════════════════════════════════════════════════════════════════════════

async def _post_linkedin(
    token: str,
    author_urn: str,
    text: str,
    media_url: str = "",
) -> dict:
    """
    STATUS: REAL (text) / PARCIAL (images require Assets upload step)
    Publica en LinkedIn via UGC Posts API.
    Requires: OAuth 2.0 token with w_member_social scope.
    author_urn: 'urn:li:person:{ID}' or 'urn:li:organization:{ID}'
    """
    if not author_urn:
        return {"status": "failed", "error": "platform_user_id (LinkedIn URN urn:li:person:ID) no configurado"}

    url     = "https://api.linkedin.com/v2/ugcPosts"
    headers = {
        "Authorization":   f"Bearer {token}",
        "Content-Type":    "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    share_content: dict = {
        "shareCommentary":    {"text": text},
        "shareMediaCategory": "NONE",
    }

    if media_url:
        # Article/URL share — simpler than asset upload
        share_content["shareMediaCategory"] = "ARTICLE"
        share_content["media"] = [{
            "status":          "READY",
            "originalUrl":     media_url,
            "description":     {"text": text[:200]},
        }]

    payload = {
        "author":               author_urn,
        "lifecycleState":       "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": share_content,
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC",
        },
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=30)) as r:
                data = await r.json()
                if r.status not in (200, 201):
                    err = data.get("message", str(data))
                    return {"status": "failed", "error": err, "http_status": r.status}
                post_id = data.get("id", "")
                return {"status": "published", "post_id": post_id, "platform": "linkedin"}
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# TIKTOK — Content Posting API v2
# ══════════════════════════════════════════════════════════════════════════════

async def _post_tiktok(
    token: str,
    caption: str,
    video_url: str = "",
) -> dict:
    """
    STATUS: PARCIAL — TikTok requires video, text-only not supported.
    Initiates a video publish via TikTok Content Posting API v2.
    Requires: video_url (publicly accessible, MP4 recommended).
    """
    if not video_url:
        return {
            "status": "skipped",
            "note":   "TikTok requires video_url. Text/image posting not supported.",
            "post_id": f"tt_text_only_{uuid.uuid4().hex[:8]}",
        }

    url     = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    payload = {
        "post_info": {
            "title":            caption[:2200],
            "privacy_level":    "SELF_ONLY",  # start as private, user can change
            "disable_duet":     False,
            "disable_comment":  False,
            "disable_stitch":   False,
        },
        "source_info": {
            "source":    "PULL_FROM_URL",
            "video_url": video_url,
        },
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=30)) as r:
                data = await r.json()
                if r.status not in (200, 201) or data.get("error", {}).get("code", "ok") != "ok":
                    err = data.get("error", {}).get("message", str(data))
                    return {"status": "failed", "error": err, "http_status": r.status}
                pub_id = data.get("data", {}).get("publish_id", "")
                return {
                    "status":     "processing",  # TikTok processes async
                    "publish_id": pub_id,
                    "platform":   "tiktok",
                    "note":       "Video processing async — check status via TikTok API",
                }
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# MAIN DISPATCHER — called by e10_social._post_to_platform_api
# ══════════════════════════════════════════════════════════════════════════════

async def post_to_platform(
    platform: str,
    token: str,
    content: str,
    media_url: str = "",
    hashtags: Optional[list] = None,
    platform_user_id: str = "",
    extra: Optional[dict] = None,
) -> dict:
    """
    STATUS: REAL for instagram/facebook/twitter/linkedin; PARCIAL for tiktok; STUB for youtube_shorts.
    Main dispatcher for e10_social.

    platform_user_id:
      instagram → IG Business User ID
      facebook  → Page ID
      twitter   → (not needed for v2 user context)
      linkedin  → 'urn:li:person:{ID}' or 'urn:li:organization:{ID}'
      tiktok    → (not needed)
      threads   → Threads User ID
    """
    if not token:
        return {
            "platform": platform,
            "status":   "queued",
            "note":     f"No OAuth token configured for {platform}. Connect via /api/e10/connect/{platform}",
            "post_id":  f"mock_{platform}_{uuid.uuid4().hex[:8]}",
        }

    tags_str = " ".join(f"#{t.lstrip('#')}" for t in (hashtags or []))
    full_text = f"{content}\n{tags_str}".strip() if tags_str else content
    extra = extra or {}

    if platform == "instagram":
        return await _post_instagram_graph(token, platform_user_id, full_text, media_url)
    if platform == "threads":
        return await _post_instagram_graph(token, platform_user_id, full_text, media_url, is_threads=True)
    if platform == "facebook":
        return await _post_facebook(token, platform_user_id, full_text, media_url)
    if platform == "twitter":
        return await _post_twitter(token, full_text, media_url)
    if platform == "linkedin":
        return await _post_linkedin(token, platform_user_id, full_text, media_url)
    if platform == "tiktok":
        return await _post_tiktok(token, full_text, media_url)
    if platform == "youtube_shorts":
        return {
            "platform": "youtube_shorts",
            "status":   "stub",
            "note":     "YouTube Shorts upload requires OAuth + video file — STUB pending implementation",
            "post_id":  f"yt_stub_{uuid.uuid4().hex[:8]}",
        }

    return {
        "platform": platform,
        "status":   "unknown_platform",
        "error":    f"Platform {platform!r} not implemented",
    }
