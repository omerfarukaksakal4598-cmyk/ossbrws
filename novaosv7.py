import sys
import json
import os
import time
import re
import io
import struct
import zipfile
import urllib.request
import urllib.parse
import subprocess
import shutil
import tempfile
import hashlib
import html
import sqlite3
from collections import deque
from urllib.parse import urljoin
from urllib import robotparser
from pathlib import Path
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

from PySide6.QtCore import QUrl, Qt, QSize, QTimer, QThread, QObject, Signal, Slot
from PySide6.QtGui import QAction, QKeySequence, QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QPushButton,
    QToolBar,
    QProgressBar,
    QTabWidget,
    QTabBar,
    QStackedWidget,
    QMenu,
    QMessageBox,
    QFileDialog,
    QInputDialog,
    QComboBox,
    QCheckBox,
    QToolButton,
    QSizePolicy,
    QScrollArea,
    QDockWidget,
    QTextBrowser,
    QListWidgetItem,
    QSlider,
    QSpinBox,
    QKeySequenceEdit,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
)
try:
    import psutil
except Exception:
    psutil = None

from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import (
    QWebEngineProfile,
    QWebEnginePage,
    QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
    QWebEngineScript,
    QWebEnginePermission,
)

try:
    from PySide6.QtWebEngineCore import QWebEngineExtensionManager
except ImportError:
    QWebEngineExtensionManager = None

APP_NAME = "NOVAOS V7"
APP_VERSION = "7.0.0"
# WhatsApp Web, OSS Browser'ın gömülü Chromium sürümünü eski görürse
# "tarayıcınız desteklenmiyor" benzeri bir uyarı gösterebilir.
# Yalnızca web.whatsapp.com için modern Chrome kimliği gönderiyoruz.
WHATSAPP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

WHATSAPP_UA_SCRIPT = r"""
(function () {
    'use strict';
    if (!/(^|\.)web\.whatsapp\.com$/i.test(location.hostname)) return;
    if (window.__OSS_WHATSAPP_UA_PATCH__) return;
    window.__OSS_WHATSAPP_UA_PATCH__ = true;

    const UA = %s;
    const APP_VERSION = UA.replace(/^Mozilla\//, '');

    try {
        Object.defineProperty(Navigator.prototype, 'userAgent', {
            configurable: true,
            get: function () { return UA; }
        });
    } catch (_) {}

    try {
        Object.defineProperty(Navigator.prototype, 'appVersion', {
            configurable: true,
            get: function () { return APP_VERSION; }
        });
    } catch (_) {}

    try {
        Object.defineProperty(Navigator.prototype, 'platform', {
            configurable: true,
            get: function () { return 'Win32'; }
        });
    } catch (_) {}

    try {
        Object.defineProperty(Navigator.prototype, 'vendor', {
            configurable: true,
            get: function () { return 'Google Inc.'; }
        });
    } catch (_) {}

    try {
        Object.defineProperty(Navigator.prototype, 'userAgentData', {
            configurable: true,
            get: function () {
                return {
                    brands: [
                        {brand: 'Chromium', version: '136'},
                        {brand: 'Google Chrome', version: '136'},
                        {brand: 'Not.A/Brand', version: '99'}
                    ],
                    mobile: false,
                    platform: 'Windows'
                };
            }
        });
    } catch (_) {}
})();
""" % json.dumps(WHATSAPP_UA)


# ============================================================
# OSS - SADECE YOUTUBE REKLAM ENGELLEME
#
# Normal sitelere dokunmaz. Interceptor yalnızca first-party alanı
# YouTube olan isteklerde çalışır. Sayfa tarafındaki script de yalnızca
# YouTube alan adlarında çalışır.
# ============================================================

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "tv.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
    "youtubekids.com",
    "www.youtubekids.com",
}

YOUTUBE_AD_HOSTS = {
    "doubleclick.net",
    "googleads.g.doubleclick.net",
    "securepubads.g.doubleclick.net",
    "googlesyndication.com",
    "pagead2.googlesyndication.com",
    "tpc.googlesyndication.com",
    "googleadservices.com",
    "adservice.google.com",
    "ads.youtube.com",
}

YOUTUBE_AD_PATH_PARTS = (
    "/pagead/",
    "/pagead2/",
    "/api/stats/ads",
    "/get_midroll_info",
    "/ptracking",
    "/ad_status",
)

YOUTUBE_AD_MEDIA_MARKERS = (
    "_ad_",
    "oad=",
    "adunit",
    "ad_break",
    "adbreak",
    "instream",
)

YOUTUBE_COSMETIC_SCRIPT = r"""
(function () {
    'use strict';

    const HOST_RE = /(^|\.)((youtube\.com)|(youtube-nocookie\.com)|(youtubekids\.com))$/i;
    if (!HOST_RE.test(location.hostname)) return;
    if (window.__OSS_YT_ADBLOCK_ONLY_V5__) return;
    window.__OSS_YT_ADBLOCK_ONLY_V5__ = true;

    function enabled() {
        try {
            return localStorage.getItem('oss_adblock_enabled') !== '0';
        } catch (_) {
            return true;
        }
    }

    function looksLikePlayerUrl(url) {
        const u = String(url || '');
        return /\/youtubei\/v1\/(player|get_watch)(?:\?|$)/i.test(u) ||
               /\/player(?:\?|$)/i.test(u);
    }

    function pruneAds(obj, depth) {
        if (!obj || typeof obj !== 'object' || depth > 14) return obj;

        if (Array.isArray(obj)) {
            for (let i = obj.length - 1; i >= 0; i--) {
                const item = obj[i];
                if (item && typeof item === 'object') pruneAds(item, depth + 1);
            }
            return obj;
        }

        for (const key of Object.keys(obj)) {
            if (key === 'adPlacements' ||
                key === 'adSlots' ||
                key === 'playerAds') {
                try { delete obj[key]; } catch (_) {}
                continue;
            }
            pruneAds(obj[key], depth + 1);
        }
        return obj;
    }

    // YouTube player responses can contain adPlacements/adSlots/playerAds.
    // Remove those fields before YouTube consumes the JSON response.
    const nativeJSONParse = JSON.parse;
    if (!JSON.__OSS_YT_JSON_PATCH__) {
        JSON.__OSS_YT_JSON_PATCH__ = true;
        JSON.parse = function (text, reviver) {
            const value = nativeJSONParse.apply(this, arguments);
            if (enabled() && typeof text === 'string' &&
                (text.includes('"adPlacements"') ||
                 text.includes('"adSlots"') ||
                 text.includes('"playerAds"'))) {
                try { return pruneAds(value, 0); } catch (_) {}
            }
            return value;
        };
    }

    // Filter the player/get_watch fetch response, but only for YouTube's
    // own player endpoints. Other websites are untouched.
    const nativeFetch = window.fetch;
    if (nativeFetch && !window.__OSS_YT_FETCH_PATCH__) {
        window.__OSS_YT_FETCH_PATCH__ = true;
        window.fetch = async function () {
            const args = arguments;
            let requestUrl = '';
            try {
                const input = args[0];
                requestUrl = typeof input === 'string'
                    ? input
                    : (input && input.url) || '';
            } catch (_) {}

            const response = await nativeFetch.apply(this, args);
            if (!enabled() || !looksLikePlayerUrl(requestUrl)) {
                return response;
            }

            try {
                const clone = response.clone();
                const text = await clone.text();
                if (!text.includes('"adPlacements"') &&
                    !text.includes('"adSlots"') &&
                    !text.includes('"playerAds"')) {
                    return response;
                }

                const json = JSON.parse(text);
                pruneAds(json, 0);
                const body = JSON.stringify(json);
                const headers = new Headers(response.headers);
                headers.delete('content-length');
                headers.delete('content-encoding');
                headers.delete('transfer-encoding');

                return new Response(body, {
                    status: response.status,
                    statusText: response.statusText,
                    headers: headers
                });
            } catch (_) {
                return response;
            }
        };
    }

    const CSS = `
        #player-ads,
        #masthead-ad,
        ytd-ad-slot-renderer,
        ytd-in-feed-ad-layout-renderer,
        ytd-promoted-sparkles-web-renderer,
        ytd-display-ad-renderer,
        ytd-banner-promo-renderer,
        ytd-action-companion-ad-renderer,
        ytd-companion-slot-renderer,
        ytd-player-legacy-desktop-watch-ads-renderer,
        ytd-statement-banner-renderer,
        ytd-search-pyv-renderer,
        ytd-promoted-video-renderer,
        .ytp-ad-overlay-container,
        .ytp-ad-text-overlay,
        .ytp-ad-image-overlay,
        .ytp-ad-message-container,
        .ytp-ad-preview-container,
        .ytp-ad-player-overlay,
        .ytp-ad-skip-ad-slot {
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
            pointer-events: none !important;
        }
    `;

    function installCss() {
        if (!enabled()) return;
        if (document.getElementById('oss-yt-adblock-css')) return;
        const style = document.createElement('style');
        style.id = 'oss-yt-adblock-css';
        style.textContent = CSS;
        (document.head || document.documentElement).appendChild(style);
    }

    function clickSkipButtons() {
        if (!enabled()) return;

        const selectors = [
            '.ytp-ad-skip-button',
            '.ytp-ad-skip-button-modern',
            '.ytp-skip-ad-button',
            '.ytp-ad-skip-button-slot button',
            '.ytp-ad-skip-button-container button',
            'button.ytp-ad-skip-button',
            'button.ytp-ad-skip-button-modern',
            '.ytp-ad-overlay-close-button',
            '.ytp-ad-overlay-close-button-modern'
        ];

        for (const selector of selectors) {
            document.querySelectorAll(selector).forEach(function (button) {
                try { button.click(); } catch (_) {}
            });
        }

        // UI language can be Turkish or English, so also check visible text.
        document.querySelectorAll('button, .ytp-button').forEach(function (el) {
            try {
                const text = (el.innerText || el.getAttribute('aria-label') || '').trim();
                if (/^(atla|skip|skip ad|reklamı geç)$/i.test(text)) {
                    el.click();
                }
            } catch (_) {}
        });
    }

    function removePageAds() {
        if (!enabled()) return;
        const selectors = [
            'ytd-ad-slot-renderer',
            'ytd-in-feed-ad-layout-renderer',
            'ytd-promoted-sparkles-web-renderer',
            'ytd-display-ad-renderer',
            'ytd-banner-promo-renderer',
            'ytd-action-companion-ad-renderer',
            'ytd-companion-slot-renderer',
            'ytd-player-legacy-desktop-watch-ads-renderer',
            '#masthead-ad'
        ];

        for (const selector of selectors) {
            document.querySelectorAll(selector).forEach(function (el) {
                try { el.remove(); } catch (_) {}
            });
        }
    }

    function playerResponsePrune() {
        if (!enabled()) return;
        try {
            if (window.ytInitialPlayerResponse) {
                pruneAds(window.ytInitialPlayerResponse, 0);
            }
        } catch (_) {}
        try {
            const p = document.getElementById('movie_player');
            if (p && typeof p.getPlayerResponse === 'function') {
                const response = p.getPlayerResponse();
                pruneAds(response, 0);
            }
        } catch (_) {}
    }

    function handleVideoAd() {
        if (!enabled()) return;
        const player = document.getElementById('movie_player');
        const video = document.querySelector('#movie_player video, video');
        if (!player) return;

        const adShowing = player.classList.contains('ad-showing') ||
                          player.classList.contains('ad-interrupting');

        // Yalnızca Skip/Kapat düğmelerini hedefle.
        // Normal videonun play/pause, currentTime veya playbackRate
        // durumuna kesinlikle müdahale etme.
        clickSkipButtons();
        if (!adShowing || !video) return;
    }

    function installPauseBridge() {
        if (window.__OSS_YT_PAUSE_BRIDGE__) return;
        window.__OSS_YT_PAUSE_BRIDGE__ = true;
        document.addEventListener('click', function (event) {
            const button = event.target && event.target.closest ? event.target.closest('.ytp-play-button') : null;
            if (!button) return;
            const player = document.getElementById('movie_player');
            if (!player) return;
            // YouTube kendi butonunu normalde yönetir; bunu yalnızca
            // tarayıcı tarafındaki click zinciri bozulursa yedek olarak kullan.
            setTimeout(function () {
                try {
                    const video = player.querySelector('video');
                    if (!video) return;
                    // Buton tıklamasının ardından gerçek oynatma durumunu değiştirmesine izin ver.
                } catch (_) {}
            }, 0);
        }, true);
    }

    function resetPlaybackRate() {
        try {
            const player = document.getElementById('movie_player');
            const video = document.querySelector('#movie_player video');
            if (video && player &&
                !player.classList.contains('ad-showing') &&
                !player.classList.contains('ad-interrupting') &&
                video.playbackRate > 4) {
                video.playbackRate = 1;
            }
        } catch (_) {}
    }

    function work() {
        if (!enabled()) return;
        installCss();
        installPauseBridge();
        removePageAds();
        playerResponsePrune();
        handleVideoAd();
        resetPlaybackRate();
    }

    function start() {
        work();
        try {
            new MutationObserver(function () { work(); }).observe(
                document.documentElement || document,
                {subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'style']}
            );
        } catch (_) {}

        setInterval(work, 300);

        document.addEventListener('yt-navigate-finish', function () {
            setTimeout(work, 50);
            setTimeout(work, 500);
            setTimeout(work, 1500);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, {once: true});
    } else {
        start();
    }
})();
"""


class OssAdBlocker(QWebEngineUrlRequestInterceptor):
    """Reklam engellemeyi yalnızca YouTube first-party sayfalarında uygular."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = True
        self.blocked_count = 0

    @staticmethod
    def _is_youtube(host):
        host = (host or '').lower().rstrip('.')
        return (
            host == 'youtube.com' or
            host.endswith('.youtube.com') or
            host == 'youtube-nocookie.com' or
            host.endswith('.youtube-nocookie.com') or
            host == 'youtubekids.com' or
            host.endswith('.youtubekids.com')
        )

    @staticmethod
    def _is_whatsapp(host):
        host = (host or '').lower().rstrip('.')
        return (
            host == 'web.whatsapp.com' or
            host.endswith('.web.whatsapp.com') or
            host == 'whatsapp.com' or
            host.endswith('.whatsapp.com') or
            host.endswith('.whatsapp.net')
        )

    @staticmethod
    def _host_matches(host, domain):
        host = (host or '').lower().rstrip('.')
        domain = domain.lower().rstrip('.')
        return host == domain or host.endswith('.' + domain)

    def interceptRequest(self, info):
        if not self.enabled:
            return

        first_party = info.firstPartyUrl()
        first_host = first_party.host().lower().rstrip('.')

        # WhatsApp Web için yalnızca bu site/subdomain isteklerinde
        # modern Chrome User-Agent ve Client-Hint başlıklarını kullan.
        # Diğer sitelerin isteklerine dokunulmaz.
        url = info.requestUrl()
        host = url.host().lower().rstrip('.')
        if self._is_whatsapp(first_host) or host == 'web.whatsapp.com' or host.endswith('.whatsapp.net'):
            try:
                info.setHttpHeader(b'User-Agent', WHATSAPP_UA.encode('utf-8'))
                info.setHttpHeader(b'Sec-CH-UA', b'\"Google Chrome\";v=\"136\", \"Chromium\";v=\"136\", \"Not.A/Brand\";v=\"99\"')
                info.setHttpHeader(b'Sec-CH-UA-Mobile', b'?0')
                info.setHttpHeader(b'Sec-CH-UA-Platform', b'\"Windows\"')
            except Exception:
                pass

        first_host = first_party.host().lower().rstrip('.')
        if not self._is_youtube(first_host):
            return

        url = info.requestUrl()
        host = url.host().lower().rstrip('.')
        path = url.path().lower()
        full = url.toString().lower()

        # Third-party ad networks are blocked ONLY while the page is YouTube.
        for domain in YOUTUBE_AD_HOSTS:
            if self._host_matches(host, domain):
                info.block(True)
                self.blocked_count += 1
                return

        # Player-side YouTube ad endpoints that can be safely discarded.
        if self._is_youtube(host) and any(part in path for part in YOUTUBE_AD_PATH_PARTS):
            info.block(True)
            self.blocked_count += 1
            return

        # Current filter lists also target YouTube's third-party media URLs
        # with explicit ad markers. Keep this narrow: normal video media is
        # not blocked merely because it comes from googlevideo.com.
        if self._host_matches(host, 'googlevideo.com'):
            if any(marker in full for marker in YOUTUBE_AD_MEDIA_MARKERS):
                try:
                    resource_type = info.resourceType()
                    is_media = 'Media' in str(resource_type)
                except Exception:
                    is_media = True
                if is_media or 'oad=' in full:
                    info.block(True)
                    self.blocked_count += 1
                    return


YOUTUBE_AD_BLOCKER = OssAdBlocker()
AD_BLOCKER = YOUTUBE_AD_BLOCKER


APP_DIR = Path.home() / "OSSBrowser"
DATA_FILE = APP_DIR / "data.json"
DOWNLOAD_DIR = Path.home() / "Downloads" / "OSSBrowser"
# Kalıcı Chromium profili: Google oturumları, çerezler, localStorage
# ve diğer normal tarayıcı verileri uygulama kapanınca korunur.
PROFILE_DIR = APP_DIR / "BrowserProfile"
PROFILE_CACHE_DIR = APP_DIR / "BrowserCache"

GOOGLE_SEARCH = "https://www.google.com/search?q={}"
SEARCH_ENGINES = {
    "Google": "https://www.google.com/search?q={}",
    "Bing": "https://www.bing.com/search?q={}",
    "DuckDuckGo": "https://duckduckgo.com/?q={}",
}
HOME_URL = "https://ossbrowser.local/home"

HOME_HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Yeni Sekme</title>
<style>
:root{--bg:#0a0f17;--panel:#121924;--panel2:#151e2b;--stroke:rgba(255,255,255,.075);--text:#f4f7fb;--muted:#8794a9;--accent:#7c5cff;--accent2:#42a5ff}
*{box-sizing:border-box}html,body{width:100%;height:100%;margin:0}body{overflow:hidden;background:radial-gradient(circle at 15% 5%,rgba(124,92,255,.13),transparent 30%),radial-gradient(circle at 85% 12%,rgba(66,165,255,.10),transparent 24%),linear-gradient(180deg,#0a0f17 0%,#090d14 100%);color:var(--text);font-family:"Segoe UI",Arial,sans-serif}
.page{width:min(1160px,92vw);height:100vh;margin:0 auto;display:flex;flex-direction:column;justify-content:center;padding:24px 0 34px}
.top{display:flex;align-items:center;justify-content:space-between;margin-bottom:28px}.engine{display:inline-flex;align-items:center;gap:9px;padding:8px 13px;border:1px solid var(--stroke);background:rgba(255,255,255,.035);border-radius:999px;color:#c4cede;font-size:12px;box-shadow:inset 0 1px 0 rgba(255,255,255,.03)}.engine-dot{width:7px;height:7px;border-radius:50%;background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:0 0 16px rgba(124,92,255,.45)}
.hero{text-align:center}.hero h1{margin:0;font-size:clamp(46px,6vw,74px);font-weight:800;letter-spacing:-4px;line-height:1}.hero h1 span{background:linear-gradient(90deg,#fff,#b6c4ff 58%,#70dcff);-webkit-background-clip:text;background-clip:text;color:transparent}.hero p{margin:12px 0 24px;color:var(--muted);font-size:14px}
.search-wrap{width:min(820px,100%);margin:0 auto;padding:7px;border-radius:22px;background:rgba(16,22,32,.88);border:1px solid rgba(255,255,255,.09);box-shadow:0 24px 70px rgba(0,0,0,.34),inset 0 1px 0 rgba(255,255,255,.03)}.search{display:flex;align-items:center;gap:7px}.search input{flex:1;min-width:0;height:54px;border:0;outline:0;background:transparent;color:#fff;padding:0 16px;font-size:17px}.search input::placeholder{color:#718097}.search button{height:48px;border:0;border-radius:16px;padding:0 23px;color:#fff;font-weight:700;font-size:14px;cursor:pointer;background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:0 10px 28px rgba(91,81,255,.28)}
.quick-head{display:flex;align-items:center;justify-content:space-between;margin:28px 0 10px}.quick-head strong{font-size:13px;color:#c5cede;font-weight:600}.manage{font-size:12px;color:#aebcff;text-decoration:none}.quick{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}.card{position:relative;min-height:88px;border:1px solid var(--stroke);border-radius:16px;overflow:hidden;background:linear-gradient(180deg,rgba(21,29,42,.95),rgba(15,21,31,.95));transition:.16s}.card:hover{transform:translateY(-2px);border-color:rgba(124,92,255,.42);background:linear-gradient(180deg,rgba(28,38,57,.98),rgba(18,25,38,.98))}.card-main{display:block;min-height:88px;padding:12px 38px 12px 13px;color:#fff;text-decoration:none}.card .icon{font-size:20px;margin-bottom:10px}.card b{display:block;font-size:14px;margin-bottom:4px;font-weight:650}.card span{display:block;color:#7e8ba0;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.remove{position:absolute;right:7px;top:7px;width:24px;height:24px;border-radius:8px;display:grid;place-items:center;color:#94a1b4;text-decoration:none;background:rgba(255,255,255,.05)}.remove:hover{color:#fff;background:rgba(239,68,68,.25)}.add-card{display:flex;align-items:center;justify-content:center;flex-direction:column;min-height:88px;border:1px dashed rgba(255,255,255,.15);border-radius:16px;color:#aeb9cb;text-decoration:none;background:rgba(255,255,255,.018)}.add-card:hover{color:#fff;border-color:rgba(124,92,255,.5);background:rgba(124,92,255,.07)}.add-card .plus{font-size:25px;margin-bottom:6px}.footer{margin-top:18px;text-align:center;color:#56647a;font-size:11px}
@media(max-width:1000px){.quick{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:620px){.page{width:92vw}.quick{grid-template-columns:repeat(2,minmax(0,1fr))}.hero h1{font-size:48px}.search input{font-size:15px}.search button{padding:0 16px}}
</style>
</head>
<body>
<div class="page">
  <div class="top"><div></div><div class="engine"><span class="engine-dot"></span><span>__SEARCH_ENGINE__</span></div></div>
  <section class="hero">
    <h1><span>__SEARCH_ENGINE__</span></h1>
    <p>Arama yap veya sık kullandığın bir siteyi aç.</p>
    <div class="search-wrap">
      <form class="search" action="__SEARCH_ACTION__" method="get">
        <input name="q" autofocus autocomplete="off" placeholder="__SEARCH_ENGINE__ ile ara veya bir adres yaz…">
        <button type="submit">Ara</button>
      </form>
    </div>
  </section>
  <div class="quick-head"><strong>Hızlı erişim</strong><a class="manage" href="oss-home://manage">Yönet</a></div>
  <div class="quick">__QUICK_CARDS__</div>
  <div class="footer">Yer imleri ve tarayıcı araçları üst çubuktan yönetilir.</div>
</div>
</body>
</html>
"""


DEFAULT_HOME_SHORTCUTS = [
    {"title": "Google", "url": "https://www.google.com/", "icon": "🔎"},
    {"title": "YouTube", "url": "https://www.youtube.com/", "icon": "▶"},
    {"title": "WhatsApp", "url": "https://web.whatsapp.com/", "icon": "◉"},
    {"title": "GitHub", "url": "https://github.com/", "icon": "◈"},
    {"title": "Haritalar", "url": "https://maps.google.com/", "icon": "⌖"},
    {"title": "Wikipedia", "url": "https://www.wikipedia.org/", "icon": "W"},
]

def build_home_html(engine_name="Google", shortcuts=None):
    engine_name = engine_name if engine_name in SEARCH_ENGINES else "Google"
    # A form action must be an endpoint, not a search template containing {}.
    form_actions = globals().get("SEARCH_FORM_ACTIONS", {})
    template = SEARCH_ENGINES.get(engine_name) or GOOGLE_SEARCH
    action = form_actions.get(engine_name, template.split("?", 1)[0])
    shortcuts = shortcuts if isinstance(shortcuts, list) else DEFAULT_HOME_SHORTCUTS
    cards = []
    for index, item in enumerate(shortcuts):
        title = str(item.get("title", "Site")).strip() or "Site"
        url = str(item.get("url", "")).strip()
        icon = str(item.get("icon", "●")).strip() or "●"
        if not is_web_url(url):
            continue
        safe_title = html.escape(title)
        safe_url = html.escape(url, quote=True)
        safe_icon = html.escape(icon)
        cards.append(
            f'<div class="card">'
            f'<a class="card-main" href="{safe_url}">'
            f'<div class="icon">{safe_icon}</div><b>{safe_title}</b>'
            f'<span>{safe_url}</span></a>'
            f'<a class="remove" href="oss-home://remove/{index}" title="Kaldır">×</a></div>'
        )
    cards.append('<a class="add-card" href="oss-home://add"><div class="plus">＋</div><div>Site ekle</div></a>')
    cards_html = "\n".join(cards)
    return (
        HOME_HTML_TEMPLATE
        .replace("__SEARCH_ENGINE__", html.escape(engine_name))
        .replace("__SEARCH_ACTION__", action)
        .replace("__QUICK_CARDS__", cards_html)
    )


def ensure_folders():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def load_data():
    ensure_folders()

    default = {
        "bookmarks": [],
        "history": [],
        "settings": {
            "search_engine": "Google",
            "nova_language_filter": "turkish_only",
            "dark_mode": True,
            "bookmark_bar": True,
            "ui_v2": True,
        },
        "session_tabs": [],
        "home_shortcuts": DEFAULT_HOME_SHORTCUTS.copy(),
    }

    if not DATA_FILE.exists():
        return default

    try:
        data = json.loads(
            DATA_FILE.read_text(encoding="utf-8")
        )

        if not isinstance(data, dict):
            return default

        data.setdefault("bookmarks", [])
        data.setdefault("history", [])
        settings = data.setdefault("settings", {})
        settings.setdefault("search_engine", "Google")
        settings.setdefault("nova_language_filter", "turkish_only")
        if "dark_mode" not in settings:
            settings["dark_mode"] = True
        settings.setdefault("bookmark_bar", True)
        settings.setdefault("ui_v2", True)
        settings.setdefault("show_back_button", True)
        settings.setdefault("show_forward_button", True)
        settings.setdefault("show_reload_button", True)
        settings.setdefault("show_home_button", True)
        settings.setdefault("show_bookmark_button", True)
        settings.setdefault("show_adblock_button", True)
        settings.setdefault("show_menu_button", True)
        settings.setdefault("show_new_tab_button", True)
        settings.setdefault("compact_toolbar", False)
        settings.setdefault("restore_session", False)
        settings.setdefault("homepage_mode", "oss")
        settings.setdefault("homepage_url", "https://www.google.com/")
        settings.setdefault("accent", "#7c5cff")
        settings.setdefault("default_zoom", 1.0)
        data.setdefault("session_tabs", [])
        shortcuts = data.setdefault("home_shortcuts", [dict(x) for x in DEFAULT_HOME_SHORTCUTS])
        if not isinstance(shortcuts, list) or not shortcuts:
            data["home_shortcuts"] = [dict(x) for x in DEFAULT_HOME_SHORTCUTS]
        else:
            cleaned = []
            for item in shortcuts:
                if isinstance(item, dict) and is_web_url(str(item.get("url", "")).strip()):
                    cleaned.append({
                        "title": str(item.get("title", item.get("url", "Site"))).strip() or str(item.get("url", "Site")),
                        "url": str(item.get("url", "")).strip(),
                        "icon": str(item.get("icon", "●")).strip() or "●",
                    })
            data["home_shortcuts"] = cleaned or [dict(x) for x in DEFAULT_HOME_SHORTCUTS]

        return data

    except Exception:
        return default


def save_data(data):
    ensure_folders()

    DATA_FILE.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=4
        ),
        encoding="utf-8"
    )


def is_web_url(text):
    try:
        parsed = urlparse(text)

        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.netloc)
        )

    except Exception:
        return False


def make_url(text, search_template=None):
    text = text.strip()

    if not text:
        return "https://www.google.com/"

    if text.startswith(
        ("http://", "https://")
    ):
        return text

    if "." in text and " " not in text:
        return "https://" + text

    template = search_template or GOOGLE_SEARCH

    return template.format(
        quote_plus(text)
    )



def apply_whatsapp_ua(profile):
    """Yalnızca WhatsApp Web sayfasında modern Chrome bilgilerini bildirir."""
    scripts = profile.scripts()
    if scripts.find("OSS WhatsApp UA"):
        return

    script = QWebEngineScript()
    script.setName("OSS WhatsApp UA")
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(True)
    script.setSourceCode(WHATSAPP_UA_SCRIPT)
    scripts.insert(script)


def configure_persistent_profile(profile):
    """OSS Browser normal sekmeleri için kalıcı Chromium profili ayarları."""
    ensure_folders()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Google gibi sitelerin giriş çerezlerini uygulama kapanışından sonra
    # saklamasını zorunlu kıl.
    profile.setPersistentStoragePath(str(PROFILE_DIR))
    profile.setCachePath(str(PROFILE_CACHE_DIR))
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
    )
    profile.setHttpCacheType(
        QWebEngineProfile.HttpCacheType.DiskHttpCache
    )
    try:
        profile.setPersistentPermissionsPolicy(
            QWebEngineProfile.PersistentPermissionsPolicy.StoreOnDisk
        )
    except AttributeError:
        pass
    install_adblock(profile)
    apply_whatsapp_ua(profile)
    return profile


def install_adblock(profile):
    """Install the OSS ad blocker and YouTube cosmetic script on a profile."""
    profile.setUrlRequestInterceptor(AD_BLOCKER)

    scripts = profile.scripts()
    existing = scripts.find("OSS YouTube Ad Blocker")
    if existing:
        return

    script = QWebEngineScript()
    script.setName("OSS YouTube Ad Blocker")
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(True)
    script.setSourceCode(YOUTUBE_COSMETIC_SCRIPT)
    scripts.insert(script)



CHROME_STORE_HOSTS = {
    "chromewebstore.google.com",
    "chrome.google.com",
}

STORE_INSTALL_SCRIPT = r"""
(function () {
    'use strict';
    if (!/^(chromewebstore\.google\.com|chrome\.google\.com)$/i.test(location.hostname)) return;
    if (!/\/(detail)\//i.test(location.pathname)) return;

    const EXT_ID = %s;
    if (!/^[a-p]{32}$/.test(EXT_ID)) return;

    function installButton() {
        try {
            let btn = document.getElementById('oss-store-install');
            if (!btn) {
                btn = document.createElement('button');
                btn.id = 'oss-store-install';
                btn.type = 'button';
                btn.textContent = 'OSS\'ye ekle';
                btn.title = 'Bu uzantıyı OSS Browser\'a yükle';
                btn.style.cssText = [
                    'position:fixed',
                    'top:18px',
                    'right:24px',
                    'z-index:2147483647',
                    'border:0',
                    'border-radius:10px',
                    'padding:12px 18px',
                    'background:#1a73e8',
                    'color:white',
                    'font:600 14px Arial,sans-serif',
                    'box-shadow:0 4px 18px rgba(0,0,0,.25)',
                    'cursor:pointer'
                ].join(';');
                btn.onmouseenter = function(){ btn.style.background = '#1558b0'; };
                btn.onmouseleave = function(){ btn.style.background = '#1a73e8'; };
                btn.onclick = function () {
                    try {
                        location.href = 'oss-extension://install/' + EXT_ID;
                    } catch (_) {}
                };
                (document.body || document.documentElement).appendChild(btn);
            }
        } catch (_) {}
    }

    installButton();
    try {
        new MutationObserver(installButton).observe(document.documentElement, {
            childList:true,
            subtree:true
        });
    } catch (_) {}
    setInterval(installButton, 1200);
})();
"""


def store_extension_id(url_text):
    if not url_text:
        return None
    m = re.search(r"(?:chromewebstore\.google\.com|chrome\.google\.com)/webstore/detail/[^/]+/([a-p]{32})(?:[/?#]|$)", url_text, re.I)
    if m:
        return m.group(1).lower()
    m = re.search(r"chromewebstore\.google\.com/detail/[^/]+/([a-p]{32})(?:[/?#]|$)", url_text, re.I)
    if m:
        return m.group(1).lower()
    return None


def build_store_install_script(extension_id):
    return STORE_INSTALL_SCRIPT % json.dumps(extension_id)


def _crx_payload_to_zip_bytes(data):
    if data[:4] == b'PK\\x03\\x04' or data[:4] == b'PK\\x05\\x06' or data[:4] == b'PK\\x07\\x08':
        return data
    if data[:4] != b'Cr24' or len(data) < 12:
        raise ValueError('İndirilen dosya CRX veya ZIP değil.')
    version = struct.unpack_from('<I', data, 4)[0]
    if version == 2:
        if len(data) < 16:
            raise ValueError('Geçersiz CRX2 dosyası.')
        pub_len, sig_len = struct.unpack_from('<II', data, 8)
        offset = 16 + pub_len + sig_len
    elif version == 3:
        header_size = struct.unpack_from('<I', data, 8)[0]
        offset = 12 + header_size
    else:
        raise ValueError(f'Desteklenmeyen CRX sürümü: {version}')
    if offset >= len(data):
        raise ValueError('CRX içeriği bulunamadı.')
    payload = data[offset:]
    if not payload.startswith(b'PK'):
        raise ValueError('CRX içindeki ZIP verisi bulunamadı.')
    return payload


def _prepare_extension_zip(raw_data, destination):
    zip_bytes = _crx_payload_to_zip_bytes(raw_data)
    with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
        names = set(zf.namelist())
        if 'manifest.json' not in names:
            raise ValueError('Uzantının kökünde manifest.json bulunamadı.')
        manifest = json.loads(zf.read('manifest.json').decode('utf-8-sig'))
        if manifest.get('manifest_version') != 3:
            raise ValueError('OSS Browser yalnızca Manifest V3 uzantılarını destekliyor.')
        # Zip içeriğini yeniden yazmadan doğrudan çıkarılmış ZIP payload'ını kaydet.
    Path(destination).write_bytes(zip_bytes)
    return manifest


class StoreExtensionWorker(QObject):
    finished = Signal(bool, str, str, str, str)

    def __init__(self, extension_id, destination):
        super().__init__()
        self.extension_id = extension_id
        self.destination = destination

    @Slot()
    def run(self):
        try:
            last_error = ''
            versions = [
                '140.0.7339.82',
                '143.0.7499.41',
            ]
            raw = None
            for version in versions:
                url = (
                    'https://clients2.google.com/service/update2/crx?'
                    'response=redirect&prod=chromium&prodversion=' + version +
                    '&acceptformat=crx3&x=id%3D' + self.extension_id + '%26installsource%3Dondemand%26uc'
                )
                req = urllib.request.Request(
                    url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                                      '(KHTML, like Gecko) Chrome/' + version + ' Safari/537.36',
                        'Accept': 'application/x-chrome-extension,application/octet-stream,*/*',
                    },
                )
                try:
                    with urllib.request.urlopen(req, timeout=30) as response:
                        data = response.read()
                    if data and len(data) > 1000 and (data[:4] == b'Cr24' or data[:2] == b'PK'):
                        raw = data
                        break
                    last_error = 'Google Web Store geçerli bir uzantı paketi döndürmedi.'
                except Exception as exc:
                    last_error = str(exc)
            if raw is None:
                raise RuntimeError(last_error or 'Uzantı indirilemedi.')

            manifest = _prepare_extension_zip(raw, self.destination)
            name = str(manifest.get('name') or 'İsimsiz uzantı')
            version = str(manifest.get('version') or '')
            self.finished.emit(True, self.destination, name, version, '')
        except Exception as exc:
            self.finished.emit(False, '', '', '', str(exc))


class BrowserPage(QWebEnginePage):
    def __init__(self, browser, profile, parent=None):
        super().__init__(profile, parent)
        self.browser = browser

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        scheme = url.scheme().lower()
        if scheme == 'oss-extension' and url.host().lower() == 'install':
            extension_id = url.path().strip('/').lower()
            if re.fullmatch(r'[a-p]{32}', extension_id):
                self.browser.install_store_extension(extension_id)
            return False
        if scheme == 'oss-home':
            action = url.host().lower()
            path = url.path().strip('/')
            if action == 'add':
                self.browser.add_home_shortcut()
            elif action == 'manage':
                self.browser.open_home_shortcuts_manager()
            elif action == 'remove':
                try:
                    index = int(path)
                    self.browser.remove_home_shortcut(index)
                except Exception:
                    pass
            elif action == 'reset':
                self.browser.reset_home_shortcuts()
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class BrowserTab(QWidget):

    def __init__(self, browser, private=False):
        super().__init__()

        self.browser = browser
        self.private = private
        self.pinned = False
        self.is_home = False

        if private:

            self.profile = QWebEngineProfile(
                self
            )
            install_adblock(self.profile)
            apply_whatsapp_ua(self.profile)

            self.profile.setPersistentCookiesPolicy(
                QWebEngineProfile
                .PersistentCookiesPolicy
                .NoPersistentCookies
            )

            self.profile.setHttpCacheType(
                QWebEngineProfile
                .HttpCacheType
                .MemoryHttpCache
            )

            page = BrowserPage(
                self.browser,
                self.profile,
                self
            )

        else:

            # Normal sekmeler aynı kalıcı profile bağlanır.
            # Böylece Google hesabı, YouTube oturumu ve diğer site çerezleri
            # uygulama yeniden açıldığında da kullanılmaya devam eder.
            self.profile = browser.get_active_profile()
            page = BrowserPage(
                self.browser,
                self.profile,
                self
            )

        settings = page.settings()

        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled,
            True
        )

        settings.setAttribute(
            QWebEngineSettings.WebAttribute.PluginsEnabled,
            True
        )

        settings.setAttribute(
            QWebEngineSettings.WebAttribute.FullScreenSupportEnabled,
            True
        )

        self.view = QWebEngineView()
        self.view.setPage(page)
        try:
            self.view.setZoomFactor(float(self.browser.data.get("settings", {}).get("default_zoom", 1.0)))
        except Exception:
            pass

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(self.view)

        self.view.urlChanged.connect(
            lambda url:
            browser.tab_url_changed(self, url)
        )

        self.view.titleChanged.connect(
            lambda title:
            browser.tab_title_changed(
                self,
                title
            )
        )

        self.view.iconChanged.connect(
            lambda icon:
            browser.tab_icon_changed(
                self,
                icon
            )
        )

        self.view.loadProgress.connect(
            lambda value:
            browser.tab_progress(
                self,
                value
            )
        )

        self.view.loadFinished.connect(
            lambda ok: self.browser.page_loaded(self) if ok else None
        )

        try:
            self.view.page().permissionRequested.connect(
                self.browser.handle_permission_requested
            )
        except Exception:
            pass

        self.view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )

        self.view.customContextMenuRequested.connect(
            self.show_context_menu
        )

        self.set_home()

    def set_home(self):
        self.is_home = True
        settings = self.browser.data.get("settings", {})
        mode = settings.get("homepage_mode", "oss")
        if mode == "custom":
            custom = str(settings.get("homepage_url", "https://www.google.com/")).strip()
            if is_web_url(custom):
                self.view.setUrl(QUrl(custom))
                return
        engine = settings.get("search_engine", "Google")
        self.view.setHtml(
            build_home_html(engine, self.browser.data.get("home_shortcuts", DEFAULT_HOME_SHORTCUTS)),
            QUrl(HOME_URL)
        )

    def show_context_menu(self, position):

        menu = QMenu(self)

        back = menu.addAction("← Geri")
        forward = menu.addAction("→ İleri")
        reload_action = menu.addAction("⟳ Yenile")

        menu.addSeparator()

        new_tab = menu.addAction(
            "Yeni sekmede aç"
        )

        copy_link = menu.addAction(
            "Adresini kopyala"
        )

        action = menu.exec(
            self.view.mapToGlobal(position)
        )

        if action == back:
            self.view.back()

        elif action == forward:
            self.view.forward()

        elif action == reload_action:
            self.view.reload()

        elif action == new_tab:

            url = self.view.url().toString()

            if url:
                self.browser.new_tab(
                    url
                )

        elif action == copy_link:

            QApplication.clipboard().setText(
                self.view.url().toString()
            )


class HistoryDialog(QDialog):

    def __init__(self, browser):

        super().__init__(browser)

        self.browser = browser

        self.setWindowTitle(
            "OSS Geçmiş"
        )

        self.resize(800, 500)

        layout = QVBoxLayout(self)

        self.list = QListWidget()

        self.list.itemDoubleClicked.connect(
            self.open_item
        )

        clear_button = QPushButton(
            "Geçmişi Temizle"
        )

        clear_button.clicked.connect(
            self.clear_history
        )

        layout.addWidget(self.list)
        layout.addWidget(clear_button)

        close = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close
        )

        close.rejected.connect(
            self.reject
        )

        layout.addWidget(close)

        self.refresh()

    def refresh(self):

        self.list.clear()

        for item in self.browser.data["history"]:

            row = QListWidgetItem(
                f'{item["time"]}\n'
                f'{item["title"]}\n'
                f'{item["url"]}'
            )

            row.setData(
                Qt.ItemDataRole.UserRole,
                item["url"]
            )

            self.list.addItem(row)

    def open_item(self, item):

        url = item.data(
            Qt.ItemDataRole.UserRole
        )

        if url:
            self.browser.new_tab(url)
            self.accept()

    def clear_history(self):

        self.browser.data["history"] = []

        self.browser.save()

        self.refresh()


class BookmarkDialog(QDialog):

    def __init__(self, browser):

        super().__init__(browser)

        self.browser = browser

        self.setWindowTitle(
            "OSS Yer İmleri"
        )

        self.resize(750, 500)

        layout = QVBoxLayout(self)

        self.list = QListWidget()

        self.list.itemDoubleClicked.connect(
            self.open_item
        )

        delete_button = QPushButton(
            "Seçili Yer İmini Sil"
        )

        delete_button.clicked.connect(
            self.delete_item
        )

        layout.addWidget(self.list)
        layout.addWidget(delete_button)

        close = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close
        )

        close.rejected.connect(
            self.reject
        )

        layout.addWidget(close)

        self.refresh()

    def refresh(self):

        self.list.clear()

        for item in self.browser.data["bookmarks"]:

            row = QListWidgetItem(
                f'{item["title"]}\n'
                f'{item["url"]}'
            )

            row.setData(
                Qt.ItemDataRole.UserRole,
                item["url"]
            )

            self.list.addItem(row)

    def open_item(self, item):

        url = item.data(
            Qt.ItemDataRole.UserRole
        )

        self.browser.new_tab(url)

        self.accept()

    def delete_item(self):

        item = self.list.currentItem()

        if not item:
            return

        url = item.data(
            Qt.ItemDataRole.UserRole
        )

        self.browser.data["bookmarks"] = [
            x
            for x in self.browser.data["bookmarks"]
            if x["url"] != url
        ]

        self.browser.save()
        self.browser.refresh_bookmark_bar()

        self.refresh()


class DownloadWidget(QWidget):

    def __init__(self, request, destination, parent=None):
        super().__init__(parent)
        self.request = request
        self.destination = Path(destination)
        self.started_at = time.monotonic()
        self.last_time = self.started_at
        self.last_bytes = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(4)

        self.name = QLabel(self.destination.name or request.downloadFileName() or "Dosya")
        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setMaximum(100)
        self.info = QLabel("İndirme başlatılıyor...")

        buttons = QHBoxLayout()
        self.pause_button = QPushButton("Duraklat")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.cancel_button = QPushButton("İptal")
        self.cancel_button.clicked.connect(self.cancel)
        self.folder_button = QPushButton("Klasör")
        self.folder_button.clicked.connect(self.open_folder)
        buttons.addWidget(self.pause_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.folder_button)
        buttons.addStretch(1)

        layout.addWidget(self.name)
        layout.addWidget(self.progress)
        layout.addWidget(self.info)
        layout.addLayout(buttons)

        request.receivedBytesChanged.connect(self.update_progress)
        request.totalBytesChanged.connect(self.update_progress)
        request.stateChanged.connect(self.state_changed)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_progress)
        self.timer.start(500)

        request.accept()
        self.update_progress()

    def update_progress(self):
        try:
            total = int(self.request.totalBytes())
            received = int(self.request.receivedBytes())
        except Exception:
            return

        if total > 0:
            percent = max(0, min(100, int(received * 100 / total)))
            self.progress.setValue(percent)

        now = time.monotonic()
        elapsed = max(0.001, now - self.started_at)
        instant_dt = max(0.001, now - self.last_time)
        delta = max(0, received - self.last_bytes)
        speed = delta / instant_dt
        if speed <= 0:
            speed = received / elapsed if received > 0 else 0

        def fmt_bytes(value):
            value = float(max(0, value))
            units = ("B", "KB", "MB", "GB")
            i = 0
            while value >= 1024 and i < len(units) - 1:
                value /= 1024.0
                i += 1
            return f"{value:.1f} {units[i]}"

        speed_text = f"{fmt_bytes(speed)}/s" if speed else "—"
        if total > 0 and speed > 0 and received <= total:
            eta = (total - received) / speed
            mins, secs = divmod(int(eta), 60)
            if mins:
                eta_text = f"{mins} dk {secs} sn"
            else:
                eta_text = f"{secs} sn"
        else:
            eta_text = "—"

        if total > 0:
            self.info.setText(
                f"{fmt_bytes(received)} / {fmt_bytes(total)}  •  {speed_text}  •  Kalan: {eta_text}"
            )
        else:
            self.info.setText(f"{fmt_bytes(received)}  •  {speed_text}")

        self.last_time = now
        self.last_bytes = received

    def state_changed(self, state):
        state_value = int(state)
        names = {
            0: "Bekliyor",
            1: "İndiriliyor",
            2: "Tamamlandı",
            3: "İptal edildi",
            4: "Hata",
        }
        self.info.setText(names.get(state_value, "Bilinmeyen durum"))
        if state_value == 2:
            self.progress.setValue(100)
            self.pause_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            self.timer.stop()
        elif state_value in (3, 4):
            self.pause_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            self.timer.stop()

    def toggle_pause(self):
        try:
            if self.request.isPaused():
                self.request.resume()
                self.pause_button.setText("Duraklat")
            else:
                self.request.pause()
                self.pause_button.setText("Devam")
        except Exception as exc:
            QMessageBox.warning(self, "OSS Browser", f"İndirme durumu değiştirilemedi:\n{exc}")

    def cancel(self):
        try:
            self.request.cancel()
            self.pause_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            self.timer.stop()
        except Exception:
            pass

    def open_folder(self):
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.destination.parent)))
        except Exception:
            pass


class DownloadsDialog(QDialog):

    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS İndirmeler")
        self.resize(820, 560)

        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)

        bottom = QHBoxLayout()
        folder = QPushButton("İndirme Klasörünü Aç")
        folder.clicked.connect(browser.open_download_folder)
        clear = QPushButton("Tamamlananları Temizle")
        clear.clicked.connect(self.clear_finished)
        close = QPushButton("Kapat")
        close.clicked.connect(self.reject)
        bottom.addWidget(folder)
        bottom.addWidget(clear)
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for widget in self.browser.download_widgets:
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, widget)

    def clear_finished(self):
        alive = []
        for widget in self.browser.download_widgets:
            try:
                state = int(widget.request.state())
            except Exception:
                state = 4
            if state == 2:
                widget.deleteLater()
            else:
                alive.append(widget)
        self.browser.download_widgets = alive
        self.refresh()


class ChromeTabsWidget(QWidget):
    """Chrome benzeri üst sekme çubuğu + ayrı içerik alanı.

    Dışarıya eski QTabWidget API'sinin ihtiyacımız olan bölümünü sunar;
    böylece tarayıcının diğer özellikleri değişmeden kalır.
    """
    currentChanged = Signal(int)
    tabCloseRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tabbar = QTabBar()
        self._tabbar.setDocumentMode(True)
        self._tabbar.setDrawBase(False)
        self._tabbar.setExpanding(False)
        self._tabbar.setElideMode(Qt.TextElideMode.ElideRight)
        self._tabbar.setMovable(True)
        self._tabbar.setTabsClosable(True)
        self._stack = QStackedWidget()
        self._tabbar.currentChanged.connect(self._on_current_changed)
        self._tabbar.tabCloseRequested.connect(lambda i: self.tabCloseRequested.emit(i))
        self._tabbar.tabMoved.connect(self._on_tab_moved)
        self._stack.currentChanged.connect(self._on_stack_changed)

    def tabBar(self):
        return self._tabbar

    def contentWidget(self):
        return self._stack

    def setTabsClosable(self, value):
        self._tabbar.setTabsClosable(value)

    def setMovable(self, value):
        self._tabbar.setMovable(value)

    def setDocumentMode(self, value):
        self._tabbar.setDocumentMode(value)

    def addTab(self, widget, text):
        index = self._tabbar.addTab(text)
        self._stack.insertWidget(index, widget)
        self.setCurrentIndex(index)
        return index

    def insertTab(self, index, widget, text):
        index = max(0, min(index, self.count()))
        self._tabbar.insertTab(index, text)
        self._stack.insertWidget(index, widget)
        return index

    def removeTab(self, index):
        if index < 0 or index >= self.count():
            return
        widget = self._stack.widget(index)
        self._tabbar.removeTab(index)
        if widget is not None:
            self._stack.removeWidget(widget)

    def count(self):
        return self._tabbar.count()

    def widget(self, index):
        return self._stack.widget(index)

    def currentWidget(self):
        return self._stack.currentWidget()

    def currentIndex(self):
        return self._tabbar.currentIndex()

    def setCurrentIndex(self, index):
        if 0 <= index < self.count():
            self._tabbar.setCurrentIndex(index)
            self._stack.setCurrentIndex(index)

    def indexOf(self, widget):
        return self._stack.indexOf(widget)

    def setTabText(self, index, text):
        self._tabbar.setTabText(index, text)

    def setTabIcon(self, index, icon):
        self._tabbar.setTabIcon(index, icon)

    def _on_current_changed(self, index):
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)
        self.currentChanged.emit(index)

    def _on_stack_changed(self, index):
        if 0 <= index < self._tabbar.count() and self._tabbar.currentIndex() != index:
            self._tabbar.setCurrentIndex(index)

    def _on_tab_moved(self, from_index, to_index):
        widget = self._stack.widget(from_index)
        if widget is None:
            return
        self._stack.removeWidget(widget)
        self._stack.insertWidget(to_index, widget)
        self._stack.setCurrentIndex(to_index)


class BrowserSettingsDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Browser Ayarları")
        self.setModal(True)
        self.setMinimumSize(980, 680)
        self.setWindowState(Qt.WindowState.WindowMaximized)

        settings = browser.data.setdefault("settings", {})

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(235)
        self.sidebar.addItems(["Genel", "Görünüm", "Sekmeler", "Gizlilik", "Gelişmiş"])
        root.addWidget(self.sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(28, 24, 28, 24)
        right.setSpacing(16)
        root.addLayout(right, 1)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        self.page_title = QLabel("Genel")
        self.page_title.setObjectName("SettingsTitle")
        title_box.addWidget(self.page_title)
        self.page_desc = QLabel("OSS Browser davranışlarını ve varsayılanlarını düzenle.")
        self.page_desc.setObjectName("SettingsDesc")
        title_box.addWidget(self.page_desc)
        header.addLayout(title_box, 1)
        right.addLayout(header)

        self.pages = QStackedWidget()
        right.addWidget(self.pages, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = QPushButton("İptal")
        apply_btn = QPushButton("Uygula")
        save_btn = QPushButton("Kaydet ve Kapat")
        cancel.clicked.connect(self.reject)
        apply_btn.clicked.connect(self.apply)
        save_btn.clicked.connect(self.accept_after_apply)
        footer.addWidget(cancel)
        footer.addWidget(apply_btn)
        footer.addWidget(save_btn)
        right.addLayout(footer)

        # Genel
        general = QWidget()
        gl = QVBoxLayout(general)
        gl.setSpacing(14)
        self.search_combo = QComboBox()
        self.search_combo.addItems(list(SEARCH_ENGINES.keys()))
        current_engine = settings.get("search_engine", "Google")
        self.search_combo.setCurrentText(current_engine if current_engine in SEARCH_ENGINES else "Google")
        gl.addWidget(self._card("Varsayılan arama motoru", "Adres çubuğu ve ana sayfa aramalarında kullanılır. Google, Bing, DuckDuckGo ve NOVA seçenekleri korunur.", self.search_combo))

        self.nova_language_combo = QComboBox()
        self.nova_language_combo.addItem("Yabancı siteleri gizle · Türkçe/Türkiye kaynakları", "turkish_only")
        self.nova_language_combo.addItem("Türkçe kaynakları önce göster", "turkish_first")
        self.nova_language_combo.addItem("Tüm diller · yabancı siteler dâhil", "all")
        current_language_filter = str(settings.get("nova_language_filter", "turkish_only"))
        filter_index = self.nova_language_combo.findData(current_language_filter)
        self.nova_language_combo.setCurrentIndex(filter_index if filter_index >= 0 else 0)
        gl.addWidget(self._card("NOVA Search sonuç dili", "Yalnızca NOVA Search sonuçlarını etkiler. Yabancı siteleri gizlemek veya tüm dilleri görmek için buradan değiştir.", self.nova_language_combo))

        home_combo = QComboBox()
        home_combo.addItems(["OSS ana sayfası", "Özel web sitesi"])
        home_combo.setCurrentIndex(1 if settings.get("homepage_mode") == "custom" else 0)
        self.home_combo = home_combo
        self.home_url = QLineEdit(str(settings.get("homepage_url", "https://www.google.com/")))
        self.home_url.setPlaceholderText("https://ornek.com/")
        gl.addWidget(self._card("Ana sayfa", "Yeni sekmede Ana Sayfa düğmesine basınca açılacak sayfayı seç.", home_combo, self.home_url))
        gl.addStretch(1)
        self.pages.addWidget(general)

        # Görünüm
        appearance = QWidget()
        al = QVBoxLayout(appearance)
        al.setSpacing(12)
        self.dark_check = QCheckBox("Koyu tema")
        self.dark_check.setChecked(bool(settings.get("dark_mode", True)))
        self.compact_check = QCheckBox("Kompakt üst çubuk")
        self.compact_check.setChecked(bool(settings.get("compact_toolbar", False)))
        self.back_button_check = QCheckBox("Geri düğmesini göster")
        self.back_button_check.setChecked(bool(settings.get("show_back_button", True)))
        self.forward_button_check = QCheckBox("İleri düğmesini göster")
        self.forward_button_check.setChecked(bool(settings.get("show_forward_button", True)))
        self.reload_button_check = QCheckBox("Yenile düğmesini göster")
        self.reload_button_check.setChecked(bool(settings.get("show_reload_button", True)))
        self.bookmark_bar_check = QCheckBox("Yer imleri çubuğunu göster")
        self.bookmark_bar_check.setChecked(bool(settings.get("bookmark_bar", True)))
        self.home_button_check = QCheckBox("Ana sayfa düğmesini göster")
        self.home_button_check.setChecked(bool(settings.get("show_home_button", True)))
        self.bookmark_button_check = QCheckBox("Yer imi düğmesini göster")
        self.bookmark_button_check.setChecked(bool(settings.get("show_bookmark_button", True)))
        self.adblock_button_check = QCheckBox("YouTube reklam engelleme düğmesini göster")
        self.adblock_button_check.setChecked(bool(settings.get("show_adblock_button", True)))
        self.menu_button_check = QCheckBox("⋮ menü düğmesini göster")
        self.menu_button_check.setChecked(bool(settings.get("show_menu_button", True)))
        self.new_tab_button_check = QCheckBox("Sekme çubuğundaki + düğmesini göster")
        self.new_tab_button_check.setChecked(bool(settings.get("show_new_tab_button", True)))
        for w in (self.dark_check, self.compact_check, self.back_button_check, self.forward_button_check, self.reload_button_check, self.bookmark_bar_check, self.home_button_check, self.bookmark_button_check, self.adblock_button_check, self.menu_button_check, self.new_tab_button_check):
            al.addWidget(w)
        self.accent_combo = QComboBox()
        accent_items = [("Mor", "#7c5cff"), ("Mavi", "#3b82f6"), ("Yeşil", "#10b981"), ("Turuncu", "#f97316"), ("Kırmızı", "#ef4444")]
        self._accent_map = {name: color for name, color in accent_items}
        for name, color in accent_items:
            self.accent_combo.addItem(name, color)
        current_accent = settings.get("accent", "#7c5cff")
        for i in range(self.accent_combo.count()):
            if self.accent_combo.itemData(i) == current_accent:
                self.accent_combo.setCurrentIndex(i)
                break
        al.addWidget(self._card("Vurgu rengi", "Buton, odak ve seçili sekme vurgusunu belirler.", self.accent_combo))
        al.addStretch(1)
        self.pages.addWidget(appearance)

        # Sekmeler
        tabs_page = QWidget()
        tl = QVBoxLayout(tabs_page)
        tl.setSpacing(12)
        self.restore_check = QCheckBox("Uygulama açılırken son oturumu geri yükle")
        self.restore_check.setChecked(bool(settings.get("restore_session", True)))
        tl.addWidget(self.restore_check)
        tl.addWidget(QLabel("Sekmeleri sürükleyerek sıralayabilir, sağ tık ile sabitleyebilirsin."))
        tl.addWidget(QLabel("Yeni sekme düğmesi sekme çubuğunun yanında bulunur."))
        tl.addStretch(1)
        self.pages.addWidget(tabs_page)

        # Gizlilik
        privacy = QWidget()
        pl = QVBoxLayout(privacy)
        pl.setSpacing(12)
        clear_history = QPushButton("Geçmişi Temizle")
        clear_history.clicked.connect(self.clear_history)
        clear_cache = QPushButton("Önbelleği Temizle")
        clear_cache.clicked.connect(self.clear_cache)
        clear_site = QPushButton("Site verilerini temizle")
        clear_site.clicked.connect(self.clear_site_data)
        pl.addWidget(clear_history)
        pl.addWidget(clear_cache)
        pl.addWidget(clear_site)
        pl.addWidget(QLabel("Google hesabı ve normal sekmelerin oturumu korunur; yalnızca buradan temizlersen silinir."))
        pl.addStretch(1)
        self.pages.addWidget(privacy)

        # Gelişmiş
        advanced = QWidget()
        dl = QVBoxLayout(advanced)
        dl.setSpacing(12)
        self.zoom_combo = QComboBox()
        for pct in (50, 67, 80, 90, 100, 110, 125, 150, 175, 200):
            self.zoom_combo.addItem(f"%{pct}", pct / 100)
        current_zoom = float(settings.get("default_zoom", 1.0))
        best = min(range(self.zoom_combo.count()), key=lambda i: abs(float(self.zoom_combo.itemData(i)) - current_zoom))
        self.zoom_combo.setCurrentIndex(best)
        dl.addWidget(self._card("Varsayılan sayfa yakınlaştırması", "Yeni sekmeler için başlangıç zoom oranı.", self.zoom_combo))
        dl.addWidget(QLabel("Tarayıcı profili: " + str(PROFILE_DIR)))
        dl.addStretch(1)
        self.pages.addWidget(advanced)

        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sidebar.currentRowChanged.connect(self._page_changed)
        self.sidebar.setCurrentRow(0)
        self.apply_window_style()

    def _card(self, title, description, *widgets):
        box = QWidget()
        box.setObjectName("SettingsCard")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(18, 16, 18, 16)
        lbl = QLabel(title)
        lbl.setObjectName("CardTitle")
        lay.addWidget(lbl)
        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setObjectName("CardDesc")
        lay.addWidget(desc)
        for widget in widgets:
            lay.addWidget(widget)
        return box

    def _page_changed(self, index):
        names = [
            ("Genel", "Arama motoru ve ana sayfa ayarları."),
            ("Görünüm", "Tema, araç çubuğu, düğmeler ve vurgu rengi."),
            ("Sekmeler", "Oturum geri yükleme ve sekme davranışı."),
            ("Gizlilik", "Geçmiş, önbellek ve site verilerini yönet."),
            ("Gelişmiş", "Varsayılan zoom ve profil bilgileri."),
        ]
        if 0 <= index < len(names):
            self.page_title.setText(names[index][0])
            self.page_desc.setText(names[index][1])

    def apply_window_style(self):
        dark = bool(self.browser.data.get("settings", {}).get("dark_mode", True))
        bg = "#0b1018" if dark else "#f5f7fb"
        panel = "#111827" if dark else "#ffffff"
        text = "#f5f7fb" if dark else "#1f2937"
        muted = "#93a0b6" if dark else "#64748b"
        border = "#263247" if dark else "#dbe2ea"
        self.setStyleSheet(f"""
            QDialog {{ background: {bg}; color: {text}; }}
            QListWidget {{ background: {panel}; color: {text}; border: 0; padding: 18px 10px; }}
            QListWidget::item {{ padding: 13px 14px; margin: 2px 0; border-radius: 9px; }}
            QListWidget::item:selected {{ background: #7c5cff; color: white; }}
            QLabel {{ color: {text}; }}
            QLabel#SettingsTitle {{ font-size: 28px; font-weight: 800; }}
            QLabel#SettingsDesc, QLabel#CardDesc {{ color: {muted}; font-size: 13px; }}
            QLabel#CardTitle {{ font-size: 16px; font-weight: 700; }}
            QWidget#SettingsCard {{ background: {panel}; border: 1px solid {border}; border-radius: 14px; }}
            QCheckBox {{ padding: 9px 4px; font-size: 14px; }}
            QComboBox, QLineEdit {{ background: {panel}; color: {text}; border: 1px solid {border}; border-radius: 9px; padding: 10px 12px; }}
            QPushButton {{ background: #7c5cff; color: white; border: 0; border-radius: 9px; padding: 10px 16px; font-weight: 600; }}
            QPushButton:hover {{ background: #8b6dff; }}
        """)

    def clear_history(self):
        self.browser.data["history"] = []
        self.browser.save()
        QMessageBox.information(self, "OSS Browser", "Geçmiş temizlendi.")

    def clear_cache(self):
        try:
            self.browser.browser_profile.clearHttpCache()
            QMessageBox.information(self, "OSS Browser", "Önbellek temizleme başlatıldı.")
        except Exception as exc:
            QMessageBox.warning(self, "OSS Browser", f"Önbellek temizlenemedi:\n{exc}")

    def clear_site_data(self):
        try:
            self.browser.browser_profile.cookieStore().deleteAllCookies()
            QMessageBox.information(self, "OSS Browser", "Site çerezleri temizleme işlemi başlatıldı. Google hesabından çıkış yapabilirsin.")
        except Exception as exc:
            QMessageBox.warning(self, "OSS Browser", f"Site verileri temizlenemedi:\n{exc}")

    def collect(self):
        s = self.browser.data.setdefault("settings", {})
        s["search_engine"] = self.search_combo.currentText()
        s["nova_language_filter"] = self.nova_language_combo.currentData() or "turkish_only"
        s["dark_mode"] = self.dark_check.isChecked()
        s["compact_toolbar"] = self.compact_check.isChecked()
        s["show_back_button"] = self.back_button_check.isChecked()
        s["show_forward_button"] = self.forward_button_check.isChecked()
        s["show_reload_button"] = self.reload_button_check.isChecked()
        s["bookmark_bar"] = self.bookmark_bar_check.isChecked()
        s["show_home_button"] = self.home_button_check.isChecked()
        s["show_bookmark_button"] = self.bookmark_button_check.isChecked()
        s["show_adblock_button"] = self.adblock_button_check.isChecked()
        s["show_menu_button"] = self.menu_button_check.isChecked()
        s["show_new_tab_button"] = self.new_tab_button_check.isChecked()
        s["restore_session"] = self.restore_check.isChecked()
        s["homepage_mode"] = "custom" if self.home_combo.currentIndex() == 1 else "oss"
        s["homepage_url"] = self.home_url.text().strip() or "https://www.google.com/"
        s["accent"] = self.accent_combo.currentData() or "#7c5cff"
        s["default_zoom"] = float(self.zoom_combo.currentData() or 1.0)

    def apply(self):
        self.collect()
        self.browser.apply_theme()
        self.browser.apply_toolbar_preferences()
        self.browser.set_bookmark_bar_visible(bool(self.browser.data["settings"].get("bookmark_bar", True)))
        self.browser.refresh_bookmark_bar()
        self.browser.refresh_home_pages()
        for i in range(self.browser.tabs.count()):
            tab = self.browser.tabs.widget(i)
            if isinstance(tab, BrowserTab):
                try:
                    tab.view.setZoomFactor(float(self.browser.data["settings"].get("default_zoom", 1.0)))
                except Exception:
                    pass
        self.browser.save()
        self.apply_window_style()

    def accept_after_apply(self):
        self.apply()
        self.accept()


class CommandCenterDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Komut Merkezi")
        self.resize(620, 440)
        self.setModal(True)

        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Komut, ayar veya özellik ara...")
        self.search.textChanged.connect(self.refresh)
        self.search.returnPressed.connect(self.run_current)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _item: self.run_current())
        layout.addWidget(self.list)

        self.commands = [
            ("Yeni Sekme", browser.new_tab),
            ("Gizli Sekme", lambda: browser.new_tab(private=True)),
            ("Son Kapatılan Sekmeyi Aç", browser.reopen_closed_tab),
            ("Yer İmleri", lambda: BookmarkDialog(browser).exec()),
            ("Geçmiş", lambda: HistoryDialog(browser).exec()),
            ("İndirmeler", lambda: DownloadsDialog(browser).exec()),
            ("Uzantılar", lambda: browser.open_extensions()),
            ("Chrome Web Mağazası", browser.open_chrome_store),
            ("Site İzinleri", lambda: browser.open_permissions()),
            ("Ayarlar", lambda: browser.open_settings()),
            ("Sayfada Bul", browser.find_in_page),
            ("PDF Kaydet", browser.save_page_pdf),
            ("Ekran Görüntüsü", browser.save_screenshot),
            ("Yakınlaştır", browser.zoom_in),
            ("Uzaklaştır", browser.zoom_out),
            ("%100 Yakınlaştırma", browser.zoom_reset),
            ("Tam Ekran", browser.toggle_fullscreen),
            ("Yer İmleri Çubuğu", browser.toggle_bookmark_bar),
            ("OSS Ayarları", lambda: browser.open_settings()),
        ]
        self.refresh()
        self.search.setFocus()

    def refresh(self):
        query = self.search.text().strip().lower()
        self.list.clear()
        for name, _callback in self.commands:
            if not query or query in name.lower():
                self.list.addItem(name)
        if self.list.count():
            self.list.setCurrentRow(0)

    def run_current(self):
        item = self.list.currentItem()
        if not item:
            return
        name = item.text()
        for command_name, callback in self.commands:
            if command_name == name:
                self.accept()
                try:
                    callback()
                except TypeError:
                    callback
                return


class PermissionDialog(QDialog):
    TYPE_NAMES = {
        1: "Mikrofon",
        2: "Kamera",
        3: "Kamera + Mikrofon",
        4: "Ekran paylaşımı",
        5: "Ekran + ses paylaşımı",
        6: "Mouse kilidi",
        7: "Bildirimler",
        8: "Konum",
        9: "Pano erişimi",
        10: "Yerel yazı tipleri",
    }
    STATE_NAMES = {1: "Sor", 2: "İzin verildi", 3: "Reddedildi"}

    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Site İzinleri")
        self.resize(820, 520)
        layout = QVBoxLayout(self)
        self.info = QLabel("Kalıcı olarak kaydedilmiş site izinleri")
        layout.addWidget(self.info)
        self.list = QListWidget()
        layout.addWidget(self.list)

        buttons = QHBoxLayout()
        grant = QPushButton("İzin Ver")
        grant.clicked.connect(self.grant_selected)
        deny = QPushButton("Reddet")
        deny.clicked.connect(self.deny_selected)
        reset = QPushButton("Sıfırla")
        reset.clicked.connect(self.reset_selected)
        refresh = QPushButton("Yenile")
        refresh.clicked.connect(self.refresh)
        close = QPushButton("Kapat")
        close.clicked.connect(self.accept)
        buttons.addWidget(grant)
        buttons.addWidget(deny)
        buttons.addWidget(reset)
        buttons.addWidget(refresh)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def permissions(self):
        try:
            return list(self.browser.browser_profile.listAllPermissions())
        except Exception:
            return []

    def refresh(self):
        self.list.clear()
        items = self.permissions()
        if not items:
            self.list.addItem("Kayıtlı site izni bulunmuyor.")
            return
        for permission in items:
            try:
                origin = permission.origin().toDisplayString()
                type_id = int(permission.permissionType())
                state_id = int(permission.state())
                label = f"{origin}  •  {self.TYPE_NAMES.get(type_id, 'Bilinmeyen')}  •  {self.STATE_NAMES.get(state_id, 'Bilinmeyen')}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, permission)
                self.list.addItem(item)
            except Exception:
                continue

    def selected_permission(self):
        item = self.list.currentItem()
        if not item:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return value

    def grant_selected(self):
        p = self.selected_permission()
        if p:
            try:
                p.grant()
            except Exception:
                pass
            self.refresh()

    def deny_selected(self):
        p = self.selected_permission()
        if p:
            try:
                p.deny()
            except Exception:
                pass
            self.refresh()

    def reset_selected(self):
        p = self.selected_permission()
        if p:
            try:
                p.reset()
            except Exception:
                pass
            self.refresh()


class ExtensionsDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Uzantılar")
        self.resize(850, 560)
        layout = QVBoxLayout(self)
        self.info = QLabel(
            "Manifest V3 uzantıları yükleyebilirsin. Chrome Web Mağazası da aşağıdaki düğmeden açılır."
        )
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_: self.update_buttons())
        layout.addWidget(self.list)

        buttons = QHBoxLayout()
        self.install_zip_button = QPushButton("ZIP / Uzantı Klasörü Kur")
        self.install_zip_button.clicked.connect(self.install_extension)
        self.store_install_button = QPushButton("Mağazadan OSS'ye Kur")
        self.store_install_button.clicked.connect(self.install_from_store_url)
        self.open_store_button = QPushButton("Chrome Web Mağazası")
        self.open_store_button.clicked.connect(browser.open_chrome_store)
        self.toggle_button = QPushButton("Etkinleştir / Devre Dışı")
        self.toggle_button.clicked.connect(self.toggle_selected)
        self.uninstall_button = QPushButton("Kaldır")
        self.uninstall_button.clicked.connect(self.uninstall_selected)
        self.close_button = QPushButton("Kapat")
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.install_zip_button)
        buttons.addWidget(self.store_install_button)
        buttons.addWidget(self.open_store_button)
        buttons.addWidget(self.toggle_button)
        buttons.addWidget(self.uninstall_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.manager = None
        try:
            self.manager = browser.browser_profile.extensionManager()
        except Exception:
            self.manager = None

        if self.manager:
            try:
                self.manager.installFinished.connect(lambda *_: self.refresh())
                self.manager.loadFinished.connect(lambda *_: self.refresh())
                self.manager.uninstallFinished.connect(lambda *_: self.refresh())
                self.manager.unloadFinished.connect(lambda *_: self.refresh())
            except Exception:
                pass

        self.refresh()

    def refresh(self):
        self.list.clear()
        if self.manager is None:
            self.list.addItem("Uzantı sistemi için Qt WebEngine 6.10 veya üzeri gerekir.")
            self.update_buttons()
            return
        try:
            extensions = self.manager.extensions()
        except Exception as exc:
            self.list.addItem(f"Uzantılar okunamadı: {exc}")
            self.update_buttons()
            return
        if not extensions:
            self.list.addItem("Yüklü uzantı yok.")
        for extension in extensions:
            try:
                state = "Açık" if extension.isEnabled() else "Kapalı"
                status = "Kurulu" if extension.isInstalled() else "Geçici"
                name = extension.name() or "İsimsiz uzantı"
                text = f"{name}  •  {state}  •  {status}"
                if extension.error():
                    text += f"  •  Hata: {extension.error()}"
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, extension.id())
                self.list.addItem(item)
            except Exception:
                continue
        self.update_buttons()

    def selected_extension(self):
        if not self.manager:
            return None
        item = self.list.currentItem()
        if not item:
            return None
        extension_id = item.data(Qt.ItemDataRole.UserRole)
        for extension in self.manager.extensions():
            try:
                if extension.id() == extension_id:
                    return extension
            except Exception:
                pass
        return None

    def update_buttons(self):
        enabled = self.manager is not None and self.list.currentItem() is not None and bool(self.selected_extension())
        self.toggle_button.setEnabled(enabled)
        self.uninstall_button.setEnabled(enabled)

    def install_extension(self):
        if not self.manager:
            QMessageBox.warning(self, "OSS Browser", "Bu özellik Qt WebEngine 6.10+ gerektiriyor.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Uzantı ZIP dosyasını seç",
            str(Path.home()),
            "Uzantı ZIP (*.zip);;Tüm Dosyalar (*.*)"
        )
        if path:
            try:
                self.manager.installExtension(path)
                self.info.setText("Uzantı kurulumu başlatıldı. Kurulum bitince liste yenilenecek.")
            except Exception as exc:
                QMessageBox.warning(self, "OSS Browser", f"Uzantı kurulamadı:\n{exc}")
            return
        folder = QFileDialog.getExistingDirectory(self, "Unpacked uzantı klasörünü seç")
        if folder:
            try:
                self.manager.installExtension(folder)
            except Exception as exc:
                QMessageBox.warning(self, "OSS Browser", f"Uzantı kurulamadı:\n{exc}")

    def install_from_store_url(self):
        url, ok = QInputDialog.getText(
            self,
            "Chrome Web Mağazası",
            "Uzantının Chrome Web Store URL'sini yapıştır:",
        )
        if not ok or not url.strip():
            return
        extension_id = store_extension_id(url.strip())
        if not extension_id:
            QMessageBox.warning(
                self,
                "OSS Browser",
                "URL içinden geçerli 32 karakterli uzantı kimliği bulunamadı."
            )
            return
        self.browser.install_store_extension(extension_id)

    def toggle_selected(self):
        extension = self.selected_extension()
        if not extension:
            return
        try:
            self.manager.setExtensionEnabled(extension, not extension.isEnabled())
        except Exception as exc:
            QMessageBox.warning(self, "OSS Browser", f"Uzantı durumu değiştirilemedi:\n{exc}")
        self.refresh()

    def uninstall_selected(self):
        extension = self.selected_extension()
        if not extension:
            return
        reply = QMessageBox.question(
            self,
            "Uzantıyı kaldır",
            f"{extension.name()} uzantısı kaldırılsın mı?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.manager.uninstallExtension(extension)
        except Exception as exc:
            QMessageBox.warning(self, "OSS Browser", f"Uzantı kaldırılamadı:\n{exc}")


class HomeShortcutsDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("Başlangıç Kısayolları")
        self.resize(760, 520)
        self.setModal(True)

        layout = QVBoxLayout(self)
        title = QLabel("Başlangıç sayfasındaki hızlı erişim sitelerini yönet")
        title.setStyleSheet("font-size:20px;font-weight:700;")
        layout.addWidget(title)
        info = QLabel("Buradan YouTube, WhatsApp ve diğer siteleri ekleyebilir, düzenleyebilir veya kaldırabilirsin.")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.itemDoubleClicked.connect(lambda _: self.edit_selected())
        layout.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        add = QPushButton("＋ Ekle")
        edit = QPushButton("Düzenle")
        delete = QPushButton("Sil")
        reset = QPushButton("Varsayılanları Geri Getir")
        close = QPushButton("Kapat")
        add.clicked.connect(self.add_item)
        edit.clicked.connect(self.edit_selected)
        delete.clicked.connect(self.delete_selected)
        reset.clicked.connect(self.reset_defaults)
        close.clicked.connect(self.accept)
        buttons.addWidget(add)
        buttons.addWidget(edit)
        buttons.addWidget(delete)
        buttons.addStretch(1)
        buttons.addWidget(reset)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for item in self.browser.data.setdefault("home_shortcuts", [dict(x) for x in DEFAULT_HOME_SHORTCUTS]):
            row = QListWidgetItem(f'{item.get("icon", "●")}  {item.get("title", "Site")}\n{item.get("url", "")}')
            row.setData(Qt.ItemDataRole.UserRole, item.get("url", ""))
            self.list.addItem(row)

    def add_item(self):
        title, ok = QInputDialog.getText(self, "Kısayol ekle", "Ad:")
        if not ok or not title.strip():
            return
        url, ok = QInputDialog.getText(self, "Kısayol ekle", "Adres:", text="https://")
        url = url.strip()
        if not ok or not is_web_url(url):
            QMessageBox.warning(self, "OSS Browser", "Geçerli bir http/https adresi gir.")
            return
        icon, ok = QInputDialog.getText(self, "Kısayol ekle", "Simge/emoji:", text="●")
        if not ok:
            icon = "●"
        self.browser.data.setdefault("home_shortcuts", []).append({"title": title.strip(), "url": url, "icon": icon.strip() or "●"})
        self.browser.save()
        self.browser.refresh_home_pages()
        self.refresh()

    def edit_selected(self):
        item = self.list.currentItem()
        if not item:
            return
        index = self.list.currentRow()
        items = self.browser.data.setdefault("home_shortcuts", [])
        if index < 0 or index >= len(items):
            return
        old = items[index]
        title, ok = QInputDialog.getText(self, "Kısayolu düzenle", "Ad:", text=str(old.get("title", "")))
        if not ok or not title.strip():
            return
        url, ok = QInputDialog.getText(self, "Kısayolu düzenle", "Adres:", text=str(old.get("url", "")))
        url = url.strip()
        if not ok or not is_web_url(url):
            QMessageBox.warning(self, "OSS Browser", "Geçerli bir http/https adresi gir.")
            return
        icon, ok = QInputDialog.getText(self, "Kısayolu düzenle", "Simge/emoji:", text=str(old.get("icon", "●")))
        if not ok:
            icon = old.get("icon", "●")
        items[index] = {"title": title.strip(), "url": url, "icon": icon.strip() or "●"}
        self.browser.save()
        self.browser.refresh_home_pages()
        self.refresh()

    def delete_selected(self):
        row = self.list.currentRow()
        if row < 0:
            return
        items = self.browser.data.setdefault("home_shortcuts", [])
        if row >= len(items):
            return
        name = items[row].get("title", "Site")
        answer = QMessageBox.question(self, "Kısayolu sil", f"{name} silinsin mi?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        items.pop(row)
        self.browser.save()
        self.browser.refresh_home_pages()
        self.refresh()

    def reset_defaults(self):
        answer = QMessageBox.question(self, "Varsayılanları geri getir", "Başlangıç kısayolları varsayılanlara döndürülsün mü?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.browser.data["home_shortcuts"] = [dict(x) for x in DEFAULT_HOME_SHORTCUTS]
        self.browser.save()
        self.browser.refresh_home_pages()
        self.refresh()


class MainWindow(QMainWindow):

    def __init__(self):

        super().__init__()

        ensure_folders()

        # BrowserProfile nesnesi, MainWindow yaşamı boyunca canlı tutulur.
        # Kalıcı depolama yolu ve çerez politikası ilk sayfa açılmadan önce
        # ayarlanır.
        self.browser_profile = QWebEngineProfile("OSS Browser Profile", self)
        configure_persistent_profile(self.browser_profile)
        try:
            self.browser_profile.extensionManager().installFinished.connect(
                self.extension_install_finished
            )
        except Exception:
            pass

        self.data = load_data()
        settings = self.data.setdefault("settings", {})
        settings.setdefault("show_back_button", True)
        settings.setdefault("show_forward_button", True)
        settings.setdefault("show_reload_button", True)
        settings.setdefault("show_home_button", True)
        settings.setdefault("show_bookmark_button", True)
        settings.setdefault("show_adblock_button", True)
        settings.setdefault("show_menu_button", True)
        settings.setdefault("show_new_tab_button", True)
        settings.setdefault("compact_toolbar", False)
        settings.setdefault("restore_session", False)
        settings.setdefault("homepage_mode", "oss")
        settings.setdefault("homepage_url", "https://www.google.com/")
        settings.setdefault("accent", "#7c5cff")
        settings.setdefault("default_zoom", 1.0)
        if not settings.get("modern_ui_dark_v1", False):
            settings["dark_mode"] = True
            settings["modern_ui_dark_v1"] = True
        self.save()

        self.download_widgets = []
        self.closed_tabs = []
        self.ad_blocker = AD_BLOCKER

        self.setWindowTitle(
            APP_NAME
        )

        self.resize(
            1450,
            900
        )

        self.setup_ui()

        self.setup_downloads()

        self.start_fresh_session()

    def setup_ui(self):
        # Chrome benzeri yerleşim: SEKME ÇUBUĞU -> NAVİGASYON -> YER İMLERİ -> SAYFA
        self.tabs = ChromeTabsWidget()
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.current_tab_changed)
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.tab_context_menu)
        self.tabs.setDocumentMode(True)

        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        # Sekme satırı: Chrome benzeri sekmeler. Yeni sekme düğmesi
        # sekmelerin DIŞINDA, sağ tarafta bulunur. Kapat düğmesi ise
        # seçili sekmenin hemen sağ kenarına dinamik olarak yerleştirilir.
        tab_row = QWidget()
        tab_row.setObjectName("TabRow")
        tab_row_layout = QHBoxLayout(tab_row)
        tab_row_layout.setContentsMargins(8, 4, 8, 3)
        tab_row_layout.setSpacing(4)

        # Sekmeler ve + aynı blokta; + son sekmenin hemen yanında görünür.
        tab_strip = QWidget(tab_row)
        tab_strip_layout = QHBoxLayout(tab_strip)
        tab_strip_layout.setContentsMargins(0, 0, 0, 0)
        tab_strip_layout.setSpacing(2)
        tabbar = self.tabs.tabBar()
        tabbar.setExpanding(False)
        tabbar.setMinimumWidth(140)
        tabbar.setMaximumWidth(980)
        tab_strip_layout.addWidget(tabbar, 0)

        self.external_new_tab_button = QToolButton(tab_strip)
        self.external_new_tab_button.setObjectName("NewTabButton")
        self.external_new_tab_button.setText("+")
        self.external_new_tab_button.setToolTip("Yeni sekme (Ctrl+T)")
        self.external_new_tab_button.setAutoRaise(True)
        self.external_new_tab_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.external_new_tab_button.setFixedSize(36, 32)
        self.external_new_tab_button.clicked.connect(self.new_tab)
        tab_strip_layout.addWidget(self.external_new_tab_button, 0)
        tab_strip_layout.addStretch(1)

        tab_row_layout.addWidget(tab_strip, 1)
        tab_row_layout.addStretch(1)
        self.tab_strip = tab_strip

        # Bu düğme layout'a dahil değildir; seçili sekmenin sağ kenarında durur.
        self.active_tab_close_button = QToolButton(tab_row)
        self.active_tab_close_button.setObjectName("ActiveTabCloseButton")
        self.active_tab_close_button.setText("×")
        self.active_tab_close_button.setToolTip("Açık sekmeyi kapat")
        self.active_tab_close_button.setAutoRaise(True)
        self.active_tab_close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.active_tab_close_button.setFixedSize(26, 26)
        self.active_tab_close_button.clicked.connect(self.close_current_tab)
        self.active_tab_close_button.raise_()

        self.tabs.currentChanged.connect(lambda _index: QTimer.singleShot(0, self.position_active_tab_close_button))
        self.tabs.currentChanged.connect(lambda _index: QTimer.singleShot(0, self.refresh_tab_strip_layout))
        self.tabs.tabBar().tabMoved.connect(lambda _a, _b: QTimer.singleShot(0, self.position_active_tab_close_button))
        self.tabs.tabBar().tabMoved.connect(lambda _a, _b: QTimer.singleShot(0, self.refresh_tab_strip_layout))
        workspace_layout.addWidget(tab_row)
        self.tab_row = tab_row

        # Navigasyon satırı
        toolbar = QToolBar("Navigasyon")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.navigation_toolbar = toolbar
        workspace_layout.addWidget(toolbar)

        def add_nav(text, tip, callback):
            action = QAction(text, self)
            action.setToolTip(tip)
            action.triggered.connect(callback)
            toolbar.addAction(action)
            return action

        self.back_action = add_nav("‹", "Geri", self.go_back)
        self.forward_action = add_nav("›", "İleri", self.go_forward)
        self.reload_action = add_nav("↻", "Yenile", self.reload)
        self.home_action = add_nav("⌂", "Ana sayfa", self.go_home)

        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("Adres yazın veya arayın…")
        self.url_bar.setClearButtonEnabled(True)
        self.url_bar.setMinimumWidth(500)
        self.url_bar.setMaximumWidth(2400)
        self.url_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.url_bar.returnPressed.connect(self.navigate)
        toolbar.addWidget(self.url_bar)

        self.bookmark_action = QAction("☆", self)
        self.bookmark_action.setToolTip("Yer imine ekle")
        self.bookmark_action.triggered.connect(self.add_bookmark)
        toolbar.addAction(self.bookmark_action)

        self.adblock_action = QAction("🛡", self)
        self.adblock_action.setToolTip("YouTube reklam engelleme açık")
        self.adblock_action.triggered.connect(self.toggle_adblock)
        toolbar.addAction(self.adblock_action)

        self.url_focus_action = QAction(self)
        self.url_focus_action.setShortcut(QKeySequence("Ctrl+L"))
        self.url_focus_action.triggered.connect(lambda: (self.url_bar.setFocus(), self.url_bar.selectAll()))
        self.addAction(self.url_focus_action)

        command_action = QAction(self)
        command_action.setShortcut(QKeySequence("Ctrl+K"))
        command_action.triggered.connect(self.open_command_center)
        self.addAction(command_action)

        fullscreen_action = QAction(self)
        fullscreen_action.setShortcut(QKeySequence("F11"))
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        self.addAction(fullscreen_action)

        more_button = QToolButton()
        more_button.setText("⋮")
        more_button.setToolTip("OSS Browser menüsü")
        more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_button.setAutoRaise(True)
        more_menu = QMenu(more_button)

        # Komut merkezi en üstte dursun; uzun araç listesi alt menülere
        # bölündüğü için ekranın altında kesilmez.
        more_menu.addAction("⌘  OSS Komut Merkezi (Ctrl+K)", self.open_command_center)
        more_menu.addSeparator()

        tab_menu = more_menu.addMenu("Sekmeler")
        tab_menu.addAction("Yeni Sekme", self.new_tab)
        tab_menu.addAction("Gizli Sekme", lambda: self.new_tab(private=True))
        tab_menu.addAction("Son Kapatılan Sekmeyi Aç", self.reopen_closed_tab)
        tab_menu.addAction("Sekmeyi Sabitle / Kaldır", self.toggle_pin_tab)
        tab_menu.addAction("Geçerli Sekmeyi Çoğalt", self.duplicate_current_tab)
        tab_menu.addAction("Geçerli Sekmeyi Kapat", self.close_current_tab)

        bookmark_menu = more_menu.addMenu("Yer İmleri")
        bookmark_menu.addAction("Yer İmlerini Aç", lambda: BookmarkDialog(self).exec())
        bookmark_menu.addAction("Yer İmi Ekle", self.add_bookmark)
        bookmark_menu.addAction("Başlangıç Kısayolları", self.open_home_shortcuts_manager)
        bookmark_menu.addAction("Yer İmleri Çubuğunu Göster / Gizle", self.toggle_bookmark_bar)

        history_menu = more_menu.addMenu("Geçmiş")
        history_menu.addAction("Geçmişi Aç", lambda: HistoryDialog(self).exec())
        history_menu.addAction("Son Kapatılan Sekmeyi Aç", self.reopen_closed_tab)

        download_menu = more_menu.addMenu("İndirmeler")
        download_menu.addAction("İndirmeleri Aç", lambda: DownloadsDialog(self).exec())
        download_menu.addAction("İndirme Klasörünü Aç", self.open_download_folder)

        extension_menu = more_menu.addMenu("Uzantılar")
        extension_menu.addAction("Uzantıları Yönet", self.open_extensions)
        extension_menu.addAction("Chrome Web Mağazası", self.open_chrome_store)

        tools_menu = more_menu.addMenu("Araçlar")
        tools_menu.addAction("Sayfada Bul", self.find_in_page)
        tools_menu.addAction("Yakınlaştır", self.zoom_in)
        tools_menu.addAction("Uzaklaştır", self.zoom_out)
        tools_menu.addAction("%100", self.zoom_reset)
        tools_menu.addSeparator()
        tools_menu.addAction("Sayfayı PDF Kaydet", self.save_page_pdf)
        tools_menu.addAction("Ekran Görüntüsü", self.save_screenshot)
        tools_menu.addAction("Tam Ekran (F11)", self.toggle_fullscreen)

        privacy_menu = more_menu.addMenu("Gizlilik ve İzinler")
        privacy_menu.addAction("Site İzinleri", self.open_permissions)
        privacy_menu.addAction("Gizlilik / Verileri Temizle", self.open_settings)

        view_menu = more_menu.addMenu("Görünüm")
        view_menu.addAction("Ayarlar", self.open_settings)
        view_menu.addAction("Yer İmleri Çubuğu", self.toggle_bookmark_bar)

        more_menu.addSeparator()
        more_menu.addAction("Ayarlar", self.open_settings)
        more_menu.addAction("OSS Hakkında", self.show_about)
        more_button.setMenu(more_menu)
        toolbar.addWidget(more_button)
        self.more_button = more_button

        # Yer imleri + sekme kontrolleri aynı satırda.
        # Böylece sekme ile ilgili hızlı kontroller, yer imlerinin hemen yanında
        # durur ve üst taraftaki arama çubuğunu kalabalıklaştırmaz.
        bookmark_row = QWidget()
        bookmark_row.setObjectName("BookmarkRow")
        bookmark_row_layout = QHBoxLayout(bookmark_row)
        bookmark_row_layout.setContentsMargins(8, 2, 8, 2)
        bookmark_row_layout.setSpacing(6)

        self.bookmark_scroll = QScrollArea()
        self.bookmark_scroll.setWidgetResizable(True)
        self.bookmark_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.bookmark_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.bookmark_scroll.setFixedHeight(36)
        self.bookmark_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.bookmark_container = QWidget()
        self.bookmark_layout = QHBoxLayout(self.bookmark_container)
        self.bookmark_layout.setContentsMargins(2, 0, 2, 0)
        self.bookmark_layout.setSpacing(5)
        self.bookmark_scroll.setWidget(self.bookmark_container)
        bookmark_row_layout.addWidget(self.bookmark_scroll, 1)

        tab_controls = QWidget()
        tab_controls.setObjectName("TabControls")
        tab_controls_layout = QHBoxLayout(tab_controls)
        tab_controls_layout.setContentsMargins(0, 0, 0, 0)
        tab_controls_layout.setSpacing(2)

        def add_tab_control(text, tip, callback, name=None):
            btn = QToolButton()
            btn.setText(text)
            btn.setToolTip(tip)
            btn.setAutoRaise(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedSize(34, 30)
            btn.clicked.connect(callback)
            tab_controls_layout.addWidget(btn)
            if name:
                setattr(self, name, btn)
            return btn

        add_tab_control("↶", "Son kapatılan sekmeyi aç", self.reopen_closed_tab)
        add_tab_control("📌", "Geçerli sekmeyi sabitle / kaldır", self.toggle_pin_tab)
        add_tab_control("⧉", "Geçerli sekmeyi çoğalt", self.duplicate_current_tab)

        bookmark_row_layout.addWidget(tab_controls, 0)
        self.tab_controls = tab_controls
        workspace_layout.addWidget(bookmark_row)
        self.bookmark_row = bookmark_row

        # Web sayfası alanı
        workspace_layout.addWidget(self.tabs.contentWidget(), 1)
        self.setCentralWidget(workspace)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(180)
        self.progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress)

        self.apply_theme()
        self.apply_toolbar_preferences()
        self.set_bookmark_bar_visible(bool(self.data.get("settings", {}).get("bookmark_bar", True)))
        self.refresh_bookmark_bar()

    def apply_toolbar_preferences(self):
        settings = self.data.get("settings", {})
        compact = bool(settings.get("compact_toolbar", False))
        self.back_action.setVisible(bool(settings.get("show_back_button", True)))
        self.forward_action.setVisible(bool(settings.get("show_forward_button", True)))
        self.reload_action.setVisible(bool(settings.get("show_reload_button", True)))
        self.home_action.setVisible(bool(settings.get("show_home_button", True)))
        self.bookmark_action.setVisible(bool(settings.get("show_bookmark_button", True)))
        self.adblock_action.setVisible(bool(settings.get("show_adblock_button", True)))
        self.more_button.setVisible(bool(settings.get("show_menu_button", True)))
        self.navigation_toolbar.setMinimumHeight(42 if compact else 50)
        self.navigation_toolbar.setMaximumHeight(46 if compact else 54)
        self.url_bar.setMinimumWidth(420 if compact else 500)
        self.url_bar.setMinimumHeight(34 if compact else 38)
        if hasattr(self, "bookmark_scroll"):
            self.bookmark_scroll.setFixedHeight(30 if compact else 36)
        if hasattr(self, "external_new_tab_button"):
            self.external_new_tab_button.setVisible(bool(settings.get("show_new_tab_button", True)))
            size = 30 if compact else 34
            self.external_new_tab_button.setFixedSize(size, size)
        if hasattr(self, "active_tab_close_button"):
            size = 26 if compact else 28
            self.active_tab_close_button.setFixedSize(size, size)
            self.position_active_tab_close_button()

    def refresh_bookmark_bar(self):
        if not hasattr(self, "bookmark_layout"):
            return

        while self.bookmark_layout.count():
            item = self.bookmark_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        bookmarks = self.data.get("bookmarks", [])

        add_button = QToolButton()
        add_button.setObjectName("BookmarkAddButton")
        add_button.setText("＋")
        add_button.setToolTip("Geçerli sayfayı yer imlerine ekle")
        add_button.setAutoRaise(False)
        add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_button.setFixedSize(32, 28)
        add_button.clicked.connect(self.add_bookmark)
        self.bookmark_layout.addWidget(add_button)

        folder_button = QToolButton()
        folder_button.setObjectName("BookmarkFolderButton")
        folder_button.setText("▾")
        folder_button.setToolTip("Yer imi klasörlerini yönet")
        folder_button.setAutoRaise(False)
        folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        folder_button.setFixedSize(28, 28)
        folder_button.clicked.connect(lambda: BookmarkFoldersDialog(self).exec())
        self.bookmark_layout.addWidget(folder_button)

        if not bookmarks:
            empty = QLabel("Henüz yer imi yok")
            empty.setObjectName("BookmarkEmpty")
            self.bookmark_layout.addWidget(empty)
        else:
            for item in bookmarks:
                title = str(item.get("title", item.get("url", "Yer İmi"))).strip() or "Yer İmi"
                if len(title) > 28:
                    title = title[:28] + "…"
                url = str(item.get("url", "")).strip()
                if not url:
                    continue
                button = QToolButton()
                button.setObjectName("BookmarkButton")
                button.setText("★ " + title)
                button.setToolTip(f"{title}\n{url}")
                button.setAutoRaise(False)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                button.setMinimumHeight(28)
                button.clicked.connect(lambda _checked=False, u=url: self.open_bookmark(u))
                self.bookmark_layout.addWidget(button)

        self.bookmark_layout.addStretch(1)

    def open_bookmark(self, url):
        """Yer imi çubuğundaki bağlantıyı aktif sekmede güvenilir biçimde aç."""
        url = str(url or "").strip()
        if not is_web_url(url):
            return
        tab = self.current_tab()
        if tab is None:
            tab = self.new_tab()
        tab.is_home = False
        tab.view.setUrl(QUrl(url))
        self.tabs.setCurrentWidget(tab)

    def refresh_tab_strip_layout(self):
        try:
            tabbar = self.tabs.tabBar()
            # Son sekmenin yanındaki + düğmesini korurken, çok sayıda sekmede
            # QTabBar'ın kendi kaydırma düğmelerinin devreye girmesine izin ver.
            hint = max(140, tabbar.sizeHint().width())
            tab_row_width = max(320, self.tab_row.width() - 30)
            target = min(980, max(140, min(hint, int(tab_row_width * 0.78))))
            tabbar.setFixedWidth(target)
        except Exception:
            pass

    def position_active_tab_close_button(self):
        """Kapat düğmesini seçili sekmenin hemen sağ kenarına yerleştir."""
        button = getattr(self, "active_tab_close_button", None)
        tabbar = self.tabs.tabBar() if hasattr(self, "tabs") else None
        if button is None or tabbar is None or self.tabs.count() <= 0:
            if button is not None:
                button.hide()
            return

        index = self.tabs.currentIndex()
        if index < 0:
            button.hide()
            return

        rect = tabbar.tabRect(index)
        if rect.width() <= 0 or rect.height() <= 0:
            button.hide()
            return

        parent = self.tab_row
        size = button.width()
        tabbar_pos = tabbar.pos()
        x = tabbar_pos.x() + rect.right() - size - 4
        y = tabbar_pos.y() + rect.top() + max(0, (rect.height() - size) // 2)

        # Sekmenin sağ tarafında, tabbar sınırları içinde tut.
        x = max(tabbar_pos.x() + 2, min(x, tabbar_pos.x() + tabbar.width() - size - 2))
        y = max(tabbar_pos.y() + 1, min(y, tabbar_pos.y() + tabbar.height() - size - 1))

        button.setGeometry(x, y, size, size)
        button.show()
        button.raise_()

    def set_bookmark_bar_visible(self, visible):
        if hasattr(self, "bookmark_scroll"):
            self.bookmark_scroll.setVisible(bool(visible))

    def toggle_bookmark_bar(self):
        visible = not self.bookmark_scroll.isVisible()
        self.set_bookmark_bar_visible(visible)
        self.data.setdefault("settings", {})["bookmark_bar"] = visible
        self.save()

    def toggle_pin_tab(self, index=None):
        if index is None:
            index = self.tabs.currentIndex()
        if index < 0:
            return
        tab = self.tabs.widget(index)
        if not isinstance(tab, BrowserTab):
            return
        tab.pinned = not getattr(tab, "pinned", False)
        current_url = tab.view.url().toString()
        if tab.pinned:
            self.tabs.removeTab(index)
            new_index = self.tabs.insertTab(0, tab, "📌 " + (tab.view.title().strip() or "Sekme"))
            self.tabs.setCurrentIndex(new_index)
        else:
            self.tab_title_changed(tab, tab.view.title())
        self.statusBar().showMessage("Sekme sabitlendi." if tab.pinned else "Sekme sabitlemesi kaldırıldı.", 1500)
        _ = current_url

    def open_settings(self):
        if hasattr(self, "settings_window") and self.settings_window and self.settings_window.isVisible():
            self.settings_window.raise_()
            self.settings_window.activateWindow()
            return
        self.settings_window = BrowserSettingsDialog(self)
        self.settings_window.showMaximized()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def open_extensions(self):
        ExtensionsDialog(self).exec()

    def open_chrome_store(self):
        self.new_tab("https://chromewebstore.google.com/")

    def page_loaded(self, tab):
        try:
            self.reinforce_adblock(tab)
        except Exception:
            pass
        try:
            self.install_store_button(tab)
        except Exception:
            pass

    def install_store_button(self, tab):
        url = tab.view.url().toString()
        extension_id = store_extension_id(url)
        if not extension_id:
            return
        tab.view.page().runJavaScript(build_store_install_script(extension_id))

    def install_store_extension(self, extension_id):
        if QWebEngineExtensionManager is None:
            QMessageBox.warning(
                self,
                "OSS Browser",
                "Uzantı sistemi için PySide6 / Qt WebEngine 6.10 veya üzeri gerekiyor."
            )
            return

        extension_id = extension_id.lower().strip()
        if not re.fullmatch(r'[a-p]{32}', extension_id):
            QMessageBox.warning(self, "OSS Browser", "Geçersiz Chrome Web Store uzantı kimliği.")
            return

        if extension_id in self.extension_threads:
            self.statusBar().showMessage("Bu uzantı zaten indiriliyor...", 1800)
            return

        reply = QMessageBox.question(
            self,
            "Uzantıyı OSS Browser'a yükle",
            "Bu Chrome Web Store uzantısı OSS Browser'a yüklenecek.\n\n"
            "Yalnızca Manifest V3 uzantıları desteklenir. Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        download_dir = APP_DIR / "ExtensionDownloads"
        download_dir.mkdir(parents=True, exist_ok=True)
        destination = download_dir / f"{extension_id}.zip"

        thread = QThread(self)
        worker = StoreExtensionWorker(extension_id, str(destination))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda ok, path, name, version, error: self.store_extension_download_finished(
                extension_id, ok, path, name, version, error
            )
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self.extension_threads[extension_id] = (thread, worker)
        self.statusBar().showMessage("Chrome Web Mağazası uzantısı indiriliyor...", 3000)
        thread.start()

    def store_extension_download_finished(self, extension_id, ok, path, name, version, error):
        thread, worker = self.extension_threads.get(extension_id, (None, None))
        if not ok:
            self.extension_threads.pop(extension_id, None)
            QMessageBox.warning(
                self,
                "Uzantı indirilemedi",
                f"{error}\n\nUzantının mağazada mevcut olduğunu ve Manifest V3 kullandığını kontrol et."
            )
            return

        self.pending_extension_enable.add(name)
        try:
            self.browser_profile.extensionManager().installExtension(path)
            self.statusBar().showMessage(f"{name} yükleniyor...", 3000)
        except Exception as exc:
            self.pending_extension_enable.discard(name)
            self.extension_threads.pop(extension_id, None)
            QMessageBox.warning(
                self,
                "Uzantı kurulamadı",
                f"{name} kurulamadı:\n{exc}"
            )
            return

        self.extension_threads.pop(extension_id, None)

    def extension_install_finished(self, extension):
        try:
            name = extension.name() or ""
            if name in self.pending_extension_enable:
                self.pending_extension_enable.discard(name)
                try:
                    self.browser_profile.extensionManager().setExtensionEnabled(extension, True)
                except Exception:
                    pass
                self.statusBar().showMessage(
                    f"Uzantı kuruldu ve etkinleştirildi: {name}",
                    4500
                )
        except Exception:
            pass

    def open_permissions(self):
        PermissionDialog(self).exec()

    def open_command_center(self):
        CommandCenterDialog(self).exec()

    def get_home_shortcuts(self):
        return self.data.setdefault("home_shortcuts", [dict(x) for x in DEFAULT_HOME_SHORTCUTS])

    def open_home_shortcuts_manager(self):
        dialog = HomeShortcutsDialog(self)
        dialog.exec()

    def add_home_shortcut(self):
        self.open_home_shortcuts_manager()

    def remove_home_shortcut(self, index):
        items = self.data.setdefault("home_shortcuts", [])
        if not (0 <= index < len(items)):
            return
        name = items[index].get("title", "Site")
        answer = QMessageBox.question(
            self, "Kısayolu sil", f"{name} başlangıç sayfasından kaldırılsın mı?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        items.pop(index)
        self.save()
        self.refresh_home_pages()

    def reset_home_shortcuts(self):
        self.data["home_shortcuts"] = [dict(x) for x in DEFAULT_HOME_SHORTCUTS]
        self.save()
        self.refresh_home_pages()


    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def show_about(self):
        QMessageBox.information(
            self,
            "OSS Browser",
            "OSS Browser V3\n\nSekmeler • Yer İmleri • İndirmeler • Uzantılar • YouTube reklam engelleme • Kalıcı oturum",
        )

    def reinforce_adblock(self, tab):
        if not self.ad_blocker.enabled:
            return

        # This extra pass is strictly YouTube-only.
        current_url = tab.view.url().toString().lower()
        if not (
            "youtube.com" in current_url
            or "youtube-nocookie.com" in current_url
            or "youtubekids.com" in current_url
        ):
            return

        tab.view.page().runJavaScript(
            """(function(){
                try {
                    document.querySelectorAll(
                        '#player-ads, ytd-ad-slot-renderer, ytd-display-ad-renderer,
                         ytd-in-feed-ad-layout-renderer, ytd-promoted-sparkles-web-renderer,
                         ytd-companion-slot-renderer, ytd-banner-promo-renderer'
                    ).forEach(function(e){ try { e.remove(); } catch(_){} });

                    document.querySelectorAll(
                        '.ytp-ad-skip-button, .ytp-ad-skip-button-modern,
                         .ytp-skip-ad-button, .ytp-ad-skip-button-slot button,
                         .ytp-ad-skip-button-container button, .ytp-ad-overlay-close-button'
                    ).forEach(function(e){ try { e.click(); } catch(_){} });

                    // YouTube oynatıcı kontrolüne müdahale etme.
                    // Özellikle normal videolarda pause/play davranışını koru.
                } catch(_) {}
            })();"""
        )

    def refresh_home_pages(self):
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, BrowserTab) and getattr(tab, "is_home", False):
                tab.set_home()
        self.statusBar().showMessage(
            "Arama motoru: " + self.data.get("settings", {}).get("search_engine", "Google"),
            1800
        )

    def setup_downloads(self):

        self.browser_profile.downloadRequested.connect(
            self.download_requested
        )

    def start_fresh_session(self):
        """Her uygulama açılışında eski açık sekmeleri geri yükleme; tek temiz sekme aç."""
        try:
            while self.tabs.count() > 0:
                widget = self.tabs.widget(self.tabs.count() - 1)
                self.tabs.removeTab(self.tabs.count() - 1)
                if widget is not None:
                    widget.deleteLater()
        except Exception:
            pass
        self.new_tab()
        self.refresh_bookmark_bar()

    def restore_session(self):
        settings = self.data.get("settings", {})
        if not bool(settings.get("restore_session", False)):
            self.start_fresh_session()
            return
        session = self.data.get("session_tabs", [])
        restored = False
        if isinstance(session, list):
            for item in session[:20]:
                if isinstance(item, dict):
                    url = item.get("url") or ""
                    if not url:
                        continue
                    self.new_tab(url, private=False, pinned=bool(item.get("pinned", False)))
                    restored = True
                elif isinstance(item, str) and item:
                    self.new_tab(item)
                    restored = True
        if not restored:
            self.new_tab()
        self.refresh_bookmark_bar()

    def save_session(self):
        session = []
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if not isinstance(tab, BrowserTab) or tab.private:
                continue
            if getattr(tab, "is_home", False):
                continue
            url = tab.view.url().toString()
            if not url or url.startswith("about:") or url == HOME_URL or url.startswith(HOME_URL + "#"):
                continue
            session.append({
                "url": url,
                "pinned": bool(getattr(tab, "pinned", False)),
            })
        self.data["session_tabs"] = session[:20]

    def handle_permission_requested(self, permission):
        try:
            if not permission.isValid():
                return
            origin = permission.origin().toDisplayString()
            type_id = int(permission.permissionType())
            type_names = {
                1: "mikrofon",
                2: "kamera",
                3: "kamera ve mikrofon",
                4: "ekran paylaşımı",
                5: "ekran ve ses paylaşımı",
                6: "mouse kilidi",
                7: "bildirim",
                8: "konum",
                9: "pano erişimi",
                10: "yerel yazı tipleri",
            }
            name = type_names.get(type_id, "site izni")
            reply = QMessageBox.question(
                self,
                "Site İzni",
                f"{origin}\n\n{ name.capitalize() } erişimine izin verilsin mi?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                permission.grant()
            else:
                permission.deny()
        except Exception as exc:
            try:
                permission.deny()
            except Exception:
                pass
            self.statusBar().showMessage(f"Site izni işlenemedi: {exc}", 2500)

    def reopen_closed_tab(self):
        if not self.closed_tabs:
            self.statusBar().showMessage("Açılacak kapatılmış sekme yok.", 2000)
            return
        url, private = self.closed_tabs.pop(0)
        self.new_tab(url, private)

    def close_current_tab(self):
        index = self.tabs.currentIndex()
        if index >= 0:
            self.close_tab(index)

    def duplicate_current_tab(self):
        tab = self.current_tab()
        if isinstance(tab, BrowserTab):
            self.new_tab(tab.view.url().toString(), getattr(tab, "private", False))

    def find_in_page(self):
        view = self.current_view()
        if not view:
            return
        text, ok = QInputDialog.getText(self, "Sayfada Bul", "Aranacak metin:")
        if ok and text:
            view.findText(text)

    def zoom_in(self):
        view = self.current_view()
        if view:
            view.setZoomFactor(min(5.0, view.zoomFactor() + 0.1))
            self.statusBar().showMessage(f"Yakınlaştırma: %{int(view.zoomFactor() * 100)}", 1500)

    def zoom_out(self):
        view = self.current_view()
        if view:
            view.setZoomFactor(max(0.25, view.zoomFactor() - 0.1))
            self.statusBar().showMessage(f"Yakınlaştırma: %{int(view.zoomFactor() * 100)}", 1500)

    def zoom_reset(self):
        view = self.current_view()
        if view:
            view.setZoomFactor(1.0)
            self.statusBar().showMessage("Yakınlaştırma: %100", 1500)

    def save_page_pdf(self):
        view = self.current_view()
        if not view:
            return
        default_name = (view.title().strip() or "oss-sayfa").replace("/", "-")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "PDF olarak kaydet",
            str(DOWNLOAD_DIR / f"{default_name}.pdf"),
            "PDF Dosyası (*.pdf)"
        )
        if not path:
            return
        try:
            view.page().printToPdf(path)
            self.statusBar().showMessage("PDF kaydediliyor: " + path, 3000)
        except Exception as exc:
            QMessageBox.warning(self, "OSS Browser", f"PDF kaydedilemedi:\n{exc}")

    def save_screenshot(self):
        view = self.current_view()
        if not view:
            return
        default_name = datetime.now().strftime("oss_%Y%m%d_%H%M%S.png")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Ekran görüntüsünü kaydet",
            str(DOWNLOAD_DIR / default_name),
            "PNG Resmi (*.png)"
        )
        if not path:
            return
        try:
            pixmap = view.grab()
            if pixmap.save(path, "PNG"):
                self.statusBar().showMessage("Ekran görüntüsü kaydedildi.", 2500)
            else:
                QMessageBox.warning(self, "OSS Browser", "Ekran görüntüsü kaydedilemedi.")
        except Exception as exc:
            QMessageBox.warning(self, "OSS Browser", f"Ekran görüntüsü alınamadı:\n{exc}")

    def open_download_folder(self):
        ensure_folders()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DOWNLOAD_DIR)))

    def apply_theme(self):
        settings = self.data.get("settings", {})
        dark = bool(settings.get("dark_mode", True))
        accent = settings.get("accent", "#7c5cff")
        if accent not in {"#7c5cff", "#3b82f6", "#10b981", "#f97316", "#ef4444"}:
            accent = "#7c5cff"

        if dark:
            root = "#090d14"
            chrome = "#0f141d"
            tabbar_bg = "#0c1119"
            tab_idle = "#151b25"
            tab_active = "#202835"
            panel = "#141b26"
            field = "#151c28"
            border = "#232d3d"
            hover = "#1b2432"
            text = "#f4f7fb"
            muted = "#93a0b5"
        else:
            root = "#f4f6f9"
            chrome = "#eef1f5"
            tabbar_bg = "#e9edf2"
            tab_idle = "#dde3ea"
            tab_active = "#ffffff"
            panel = "#ffffff"
            field = "#ffffff"
            border = "#d4dbe5"
            hover = "#e7edf5"
            text = "#1f2937"
            muted = "#667085"

        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {root}; color: {text}; }}
            QWidget#TabRow {{ background: {tabbar_bg}; border: 0; border-bottom: 1px solid {border}; }}
            QWidget#BookmarkRow {{ background: {chrome}; border-top: 1px solid rgba(255,255,255,.02); border-bottom: 1px solid {border}; }}
            QWidget#TabControls {{ background: transparent; }}

            QTabBar {{ background: transparent; qproperty-drawBase: false; }}
            QTabBar::tab {{
                color: {muted}; background: {tab_idle}; border: 1px solid transparent;
                padding: 8px 14px; min-width: 150px; max-width: 250px; min-height: 30px;
                margin: 5px 3px 0 0; border-top-left-radius: 11px; border-top-right-radius: 11px;
            }}
            QTabBar::tab:hover:!selected {{ background: {hover}; color: {text}; }}
            QTabBar::tab:selected {{ color: {text}; background: {tab_active}; border-color: {border}; border-bottom-color: {tab_active}; }}
            QTabBar::close-button {{ width: 14px; height: 14px; margin-left: 6px; }}

            QToolBar {{ background: {chrome}; border: 0; padding: 5px 9px; spacing: 3px; min-height: 48px; }}
            QToolButton {{ color: {text}; background: transparent; border: 0; border-radius: 9px; padding: 7px 10px; font-size: 15px; min-width: 30px; }}
            QToolButton:hover {{ background: {hover}; }}
            QToolButton:pressed {{ background: {border}; }}
            QToolButton#NewTabButton {{ color: {text}; background: {panel}; border: 1px solid {border}; border-radius: 9px; font-size: 18px; padding: 0; }}
            QToolButton#NewTabButton:hover {{ background: {hover}; border-color: {accent}; }}
            QToolButton#ActiveTabCloseButton {{ color: {muted}; background: transparent; border: 0; border-radius: 7px; padding: 0; }}
            QToolButton#ActiveTabCloseButton:hover {{ color: #ffffff; background: rgba(239,68,68,.25); }}
            QToolButton#BookmarkAddButton, QToolButton#BookmarkFolderButton {{ background: {panel}; border: 1px solid {border}; }}
            QToolButton#BookmarkAddButton:hover, QToolButton#BookmarkFolderButton:hover {{ background: {hover}; border-color: {accent}; }}
            QToolButton#BookmarkButton {{ background: transparent; border: 1px solid transparent; color: {muted}; padding: 5px 10px; min-height: 28px; }}
            QToolButton#BookmarkButton:hover {{ color: {text}; background: {hover}; border-color: {border}; }}

            QLineEdit {{ min-height: 40px; padding: 0 16px; border: 1px solid {border}; border-radius: 15px; background: {field}; color: {text}; selection-background-color: {accent}; font-size: 14px; }}
            QLineEdit:focus {{ border-color: {accent}; background: {panel}; }}
            QScrollArea {{ background: transparent; }}
            QLabel#BookmarkEmpty {{ color: {muted}; padding-left: 8px; }}

            QStackedWidget {{ background: {root}; border: 0; }}
            QStatusBar {{ background: {chrome}; color: {muted}; border-top: 1px solid {border}; }}
            QMenu {{ background: {panel}; color: {text}; border: 1px solid {border}; padding: 6px; }}
            QMenu::item {{ padding: 9px 18px; border-radius: 7px; }}
            QMenu::item:selected {{ background: {hover}; }}
            QProgressBar {{ background: {field}; border: 0; border-radius: 6px; text-align: center; color: {text}; min-height: 8px; max-height: 8px; }}
            QProgressBar::chunk {{ background: {accent}; border-radius: 6px; }}
            QScrollBar:horizontal {{ height: 7px; background: transparent; margin: 0 10px; }}
            QScrollBar::handle:horizontal {{ background: {border}; min-width: 40px; border-radius: 3px; }}
            QToolTip {{ background: {panel}; color: {text}; border: 1px solid {border}; padding: 6px; }}
        """)

    def current_tab(self):

        widget = self.tabs.currentWidget()

        if isinstance(
            widget,
            BrowserTab
        ):
            return widget

        return None

    def current_view(self):

        tab = self.current_tab()

        if tab:
            return tab.view

        return None

    def new_tab(
        self,
        url=None,
        private=False,
        pinned=False
    ):

        tab = BrowserTab(
            self,
            private
        )
        tab.pinned = bool(pinned and not private)

        prefix = "🕶 " if private else ("📌 " if tab.pinned else "")
        title = prefix + ("Gizli" if private else "Yeni Sekme")

        index = self.tabs.addTab(tab, title)
        if tab.pinned and index != 0:
            self.tabs.removeTab(index)
            index = self.tabs.insertTab(0, tab, title)

        self.tabs.setCurrentIndex(index)

        if url:
            tab.is_home = False
            tab.view.setUrl(QUrl(url))

        QTimer.singleShot(0, self.refresh_tab_strip_layout)
        QTimer.singleShot(0, self.position_active_tab_close_button)
        return tab

    def close_tab(self, index):

        if self.tabs.count() == 1:
            return

        widget = self.tabs.widget(
            index
        )

        if isinstance(widget, BrowserTab):
            url = widget.view.url().toString()
            if url and url != HOME_URL and not url.startswith(HOME_URL + "#"):
                self.closed_tabs.insert(0, (url, widget.private))
                self.closed_tabs = self.closed_tabs[:20]

        self.tabs.removeTab(
            index
        )

        widget.deleteLater()
        QTimer.singleShot(0, self.refresh_tab_strip_layout)
        QTimer.singleShot(0, self.position_active_tab_close_button)

    def current_tab_changed(self, index):

        view = self.current_view()

        if not view:
            return

        url = view.url().toString()

        if url == HOME_URL or url.startswith(HOME_URL + "#"):
            self.url_bar.clear()
        else:
            self.url_bar.setText(url)

        self.update_navigation()

    def tab_url_changed(
        self,
        tab,
        url
    ):

        url_text = url.toString()
        custom_home = str(self.data.get("settings", {}).get("homepage_url", "")).strip()
        is_home = url_text == HOME_URL or url_text.startswith(HOME_URL + "#") or (custom_home and url_text == custom_home and getattr(tab, "is_home", False))
        tab.is_home = bool(is_home)

        if self.current_tab() is tab:

            if is_home:
                self.url_bar.clear()
            else:
                self.url_bar.setText(url_text)

            self.update_navigation()

        self.add_history(
            tab,
            url
        )

    def tab_title_changed(
        self,
        tab,
        title
    ):

        index = self.tabs.indexOf(
            tab
        )

        if index < 0:
            return

        if tab.private:
            prefix = "🕶 "
        elif getattr(tab, "pinned", False):
            prefix = "📌 "
        else:
            prefix = ""

        title = (
            title.strip()
            or "Yeni Sekme"
        )

        if len(title) > 25:
            title = title[:25] + "..."

        self.tabs.setTabText(
            index,
            prefix + title
        )

    def tab_icon_changed(
        self,
        tab,
        icon
    ):

        index = self.tabs.indexOf(
            tab
        )

        if index >= 0 and not icon.isNull():

            self.tabs.setTabIcon(
                index,
                icon
            )

    def tab_progress(
        self,
        tab,
        value
    ):

        if self.current_tab() is tab:

            self.progress.setValue(
                value
            )

            self.progress.setVisible(
                value < 100
            )

    def update_navigation(self):

        view = self.current_view()

        if not view:
            return

        self.statusBar().showMessage(
            ""
        )

    def navigate(self):

        text = self.url_bar.text()

        engine_name = self.data.get("settings", {}).get("search_engine", "Google")
        search_template = SEARCH_ENGINES.get(engine_name, GOOGLE_SEARCH)
        url = make_url(
            text,
            search_template
        )

        view = self.current_view()

        if view:

            view.setUrl(
                QUrl(url)
            )

    def go_back(self):

        view = self.current_view()

        if view:
            view.back()

    def go_forward(self):

        view = self.current_view()

        if view:
            view.forward()

    def reload(self):

        view = self.current_view()

        if view:
            view.reload()

    def go_home(self):

        tab = self.current_tab()

        if not tab:
            tab = self.new_tab()

        tab.set_home()

        self.url_bar.clear()

    def add_bookmark(self):
        view = self.current_view()
        if not view:
            return

        url = view.url().toString().strip()
        if not is_web_url(url) or url == HOME_URL:
            QMessageBox.information(self, "Yer İmi", "Bu sayfa yer imlerine eklenemez.")
            return

        bookmarks = self.data.setdefault("bookmarks", [])
        for item in bookmarks:
            if str(item.get("url", "")).strip() == url:
                self.refresh_bookmark_bar()
                self.statusBar().showMessage("Bu sayfa zaten yer imlerinde.", 2200)
                return

        title = (view.title() or "").strip() or url
        folder = "Genel"
        folders = self.data.setdefault("bookmark_folders", ["Genel"])
        if folders:
            current_folder = str(folders[0] or "Genel")
            if current_folder in folders:
                folder = current_folder

        bookmarks.insert(0, {"title": title, "url": url, "folder": folder})
        self.save()
        self.refresh_bookmark_bar()
        self.statusBar().showMessage("Yer imine eklendi.", 2200)

    def add_history(
        self,
        tab,
        url
    ):

        if tab.private:
            return

        text = url.toString()

        if text == HOME_URL or text.startswith(HOME_URL + "#"):
            return

        if not is_web_url(text):
            return

        title = (
            tab.view.title().strip()
            or text
        )

        history = self.data["history"]

        if (
            history
            and history[0]["url"] == text
        ):
            return

        history.insert(
            0,
            {
                "title": title,
                "url": text,
                "time": datetime.now().strftime(
                    "%d.%m.%Y %H:%M"
                )
            }
        )

        self.data["history"] = history[:500]

        self.save()

    def download_requested(
        self,
        request
    ):

        ensure_folders()

        filename = (
            request.downloadFileName()
            or "indirilen_dosya"
        )

        destination = (
            DOWNLOAD_DIR / filename
        )

        number = 1

        while destination.exists():

            destination = (
                DOWNLOAD_DIR
                /
                f"{Path(filename).stem}"
                f" ({number})"
                f"{Path(filename).suffix}"
            )

            number += 1

        request.setDownloadDirectory(
            str(destination.parent)
        )

        request.setDownloadFileName(
            destination.name
        )

        widget = DownloadWidget(
            request,
            destination,
            self
        )

        self.download_widgets.insert(
            0,
            widget
        )

        self.statusBar().showMessage(
            "İndirme başladı: "
            + destination.name
        )

    def tab_context_menu(
        self,
        position
    ):

        index = self.tabs.tabBar().tabAt(
            position
        )

        if index < 0:
            return

        menu = QMenu(
            self
        )

        tab_widget = self.tabs.widget(index)
        pin_label = "Sabitlemeyi Kaldır" if isinstance(tab_widget, BrowserTab) and getattr(tab_widget, "pinned", False) else "Sekmeyi Sabitle"

        close_action = menu.addAction("Sekmeyi Kapat")
        duplicate_action = menu.addAction("Sekmeyi Çoğalt")
        pin_action = menu.addAction(pin_label)
        reopen_action = menu.addAction("Son Kapatılan Sekmeyi Aç")
        new_action = menu.addAction("Yeni Sekme")

        action = menu.exec(
            self.tabs.tabBar().mapToGlobal(
                position
            )
        )

        if action == close_action:

            self.close_tab(index)

        elif action == pin_action:

            self.toggle_pin_tab(index)

        elif action == reopen_action:

            self.reopen_closed_tab()

        elif action == duplicate_action:

            tab = self.tabs.widget(
                index
            )

            if isinstance(
                tab,
                BrowserTab
            ):

                self.new_tab(
                    tab.view.url().toString(),
                    tab.private
                )

        elif action == new_action:

            self.new_tab()

    def toggle_adblock(self):
        self.ad_blocker.enabled = not self.ad_blocker.enabled

        if self.ad_blocker.enabled:
            self.adblock_action.setToolTip("YouTube reklam engelleme açık")
            self.statusBar().showMessage("YouTube reklam engelleme açıldı.", 2500)
        else:
            self.adblock_action.setToolTip("YouTube reklam engelleme kapalı")
            self.statusBar().showMessage("YouTube reklam engelleme kapatıldı.", 2500)

        # Only YouTube tabs receive the page-side switch/reload.
        value = "1" if self.ad_blocker.enabled else "0"
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if not isinstance(tab, BrowserTab):
                continue

            url = tab.view.url().toString().lower()
            if not (
                "youtube.com" in url
                or "youtube-nocookie.com" in url
                or "youtubekids.com" in url
            ):
                continue

            tab.view.page().runJavaScript(
                f"try{{localStorage.setItem('oss_adblock_enabled','{value}');}}catch(e){{}};location.reload();"
            )

    def save(self):

        save_data(
            self.data
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.position_active_tab_close_button)

    def closeEvent(self, event):

        self.save_session()
        self.save()

        view = self.current_view()

        if view:
            view.stop()

        event.accept()


# ============================================================
# OSS BROWSER V4 - EK MODÜLLER
# Sekme Grupları • Oturumlar • Sekme Arama • Gizlilik Merkezi
# Gelişmiş İndirmeler • Profiller • Komut Merkezi • Yer İmi Klasörleri
# Tema Merkezi
# ============================================================


def _oss_v4_safe_name(value):
    value = re.sub(r"[^A-Za-z0-9ğüşöçıİĞÜŞÖÇ _-]+", "_", str(value).strip())
    value = re.sub(r"\s+", " ", value).strip(" ._")
    return value[:60] or "Profil"


def _oss_v4_init_state(browser):
    data = browser.data
    settings = data.setdefault("settings", {})
    data.setdefault("tab_groups", {})
    data.setdefault("saved_sessions", {})
    data.setdefault("bookmark_folders", ["Genel"])
    data.setdefault("profiles", [{"name": "Default"}])
    data.setdefault("profile_bookmarks", {})
    data.setdefault("theme_presets", {})
    if "active_profile" not in settings:
        settings["active_profile"] = "Default"
    if not any(str(x.get("name", "")) == "Default" for x in data["profiles"] if isinstance(x, dict)):
        data["profiles"].insert(0, {"name": "Default"})
    browser.active_profile_name = str(settings.get("active_profile") or "Default")
    browser._oss_profile_cache = {"Default": browser.browser_profile}
    browser._oss_v4_initialized = True
    browser.save()


def _oss_v4_get_active_profile(browser):
    name = getattr(browser, "active_profile_name", "Default") or "Default"
    if name == "Default":
        return browser.browser_profile

    cache = getattr(browser, "_oss_profile_cache", None)
    if cache is None:
        cache = {"Default": browser.browser_profile}
        browser._oss_profile_cache = cache

    if name in cache:
        return cache[name]

    profile_root = APP_DIR / "Profiles"
    profile_root.mkdir(parents=True, exist_ok=True)
    safe = _oss_v4_safe_name(name)
    storage = profile_root / safe
    cache_dir = profile_root / (safe + "_cache")
    storage.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    profile = QWebEngineProfile("OSS Browser - " + name, browser)
    profile.setPersistentStoragePath(str(storage))
    profile.setCachePath(str(cache_dir))
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
    )
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
    try:
        profile.setPersistentPermissionsPolicy(
            QWebEngineProfile.PersistentPermissionsPolicy.StoreOnDisk
        )
    except Exception:
        pass
    install_adblock(profile)
    apply_whatsapp_ua(profile)
    try:
        profile.downloadRequested.connect(browser.download_requested)
    except Exception:
        pass
    try:
        profile.featurePermissionRequested.connect(browser.handle_permission_requested)
    except Exception:
        pass
    cache[name] = profile
    return profile


def _oss_v4_switch_profile(browser, name):
    names = [str(x.get("name", "")) for x in browser.data.get("profiles", []) if isinstance(x, dict)]
    if name not in names:
        return
    browser.active_profile_name = name
    browser.data.setdefault("settings", {})["active_profile"] = name
    browser.save()
    browser.statusBar().showMessage(
        f"Aktif profil: {name}. Yeni sekmeler bu profili kullanacak.", 3000
    )


def _oss_v4_profile_names(browser):
    return [str(x.get("name", "")) for x in browser.data.get("profiles", []) if isinstance(x, dict) and x.get("name")]


def _oss_v4_save_current_session(browser):
    session = []
    for i in range(browser.tabs.count()):
        tab = browser.tabs.widget(i)
        if not isinstance(tab, BrowserTab) or tab.private:
            continue
        url = tab.view.url().toString()
        if not url or url.startswith("about:") or url == HOME_URL or url.startswith(HOME_URL + "#"):
            continue
        session.append({
            "url": url,
            "pinned": bool(getattr(tab, "pinned", False)),
            "title": tab.view.title().strip(),
        })
    return session[:40]


class TabSearchDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Sekme Arama")
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Sekme adı veya adres ara...")
        self.search.textChanged.connect(self.refresh)
        self.search.returnPressed.connect(self.open_selected)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self.open_selected())
        layout.addWidget(self.list)
        close = QPushButton("Kapat")
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self.refresh()
        self.search.setFocus()

    def refresh(self):
        query = self.search.text().strip().lower()
        self.list.clear()
        for i in range(self.browser.tabs.count()):
            tab = self.browser.tabs.widget(i)
            if not isinstance(tab, BrowserTab):
                continue
            title = tab.view.title().strip() or "Yeni Sekme"
            url = tab.view.url().toString()
            text = f"{i + 1}. {title}  •  {url}"
            if query and query not in title.lower() and query not in url.lower():
                continue
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def open_selected(self):
        item = self.list.currentItem()
        if not item:
            return
        index = int(item.data(Qt.ItemDataRole.UserRole))
        if 0 <= index < self.browser.tabs.count():
            self.browser.tabs.setCurrentIndex(index)
            self.accept()


class TabGroupsDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Sekme Grupları")
        self.resize(840, 560)
        layout = QVBoxLayout(self)
        self.info = QLabel("Açık sekmeleri isimli gruplar halinde kaydet ve tek tıkla yeniden aç.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.list = QListWidget()
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        save_btn = QPushButton("Mevcut Sekmeleri Gruba Kaydet")
        save_btn.clicked.connect(self.save_group)
        open_btn = QPushButton("Grubu Aç")
        open_btn.clicked.connect(self.open_group)
        delete_btn = QPushButton("Sil")
        delete_btn.clicked.connect(self.delete_group)
        close_btn = QPushButton("Kapat")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(save_btn)
        buttons.addWidget(open_btn)
        buttons.addWidget(delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        self.list.clear()
        groups = self.browser.data.setdefault("tab_groups", {})
        if not groups:
            self.list.addItem("Henüz sekme grubu yok.")
            return
        for name, tabs in groups.items():
            item = QListWidgetItem(f"{name}  •  {len(tabs)} sekme")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
        self.list.setCurrentRow(0)

    def save_group(self):
        name, ok = QInputDialog.getText(self, "Sekme Grubu", "Grup adı:")
        name = name.strip()
        if not ok or not name:
            return
        self.browser.data.setdefault("tab_groups", {})[name] = _oss_v4_save_current_session(self.browser)
        self.browser.save()
        self.refresh()

    def open_group(self):
        item = self.list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        group = self.browser.data.get("tab_groups", {}).get(name, [])
        for entry in group:
            if isinstance(entry, dict) and entry.get("url"):
                self.browser.new_tab(entry["url"], private=False, pinned=bool(entry.get("pinned")))
        self.browser.statusBar().showMessage(f"Sekme grubu açıldı: {name}", 2200)

    def delete_group(self):
        item = self.list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        self.browser.data.setdefault("tab_groups", {}).pop(name, None)
        self.browser.save()
        self.refresh()


class SessionsDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Kayıtlı Oturumlar")
        self.resize(820, 560)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        save_btn = QPushButton("Mevcut Oturumu Kaydet")
        save_btn.clicked.connect(self.save_session)
        open_btn = QPushButton("Oturumu Aç")
        open_btn.clicked.connect(self.open_session)
        delete_btn = QPushButton("Sil")
        delete_btn.clicked.connect(self.delete_session)
        close_btn = QPushButton("Kapat")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(save_btn)
        buttons.addWidget(open_btn)
        buttons.addWidget(delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        self.list.clear()
        sessions = self.browser.data.setdefault("saved_sessions", {})
        if not sessions:
            self.list.addItem("Kayıtlı oturum yok.")
            return
        for name, tabs in sessions.items():
            item = QListWidgetItem(f"{name}  •  {len(tabs)} sekme")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
        self.list.setCurrentRow(0)

    def save_session(self):
        name, ok = QInputDialog.getText(self, "Oturum Kaydet", "Oturum adı:")
        name = name.strip()
        if not ok or not name:
            return
        self.browser.data.setdefault("saved_sessions", {})[name] = _oss_v4_save_current_session(self.browser)
        self.browser.save()
        self.refresh()

    def open_session(self):
        item = self.list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        for entry in self.browser.data.get("saved_sessions", {}).get(name, []):
            if isinstance(entry, dict) and entry.get("url"):
                self.browser.new_tab(entry["url"], pinned=bool(entry.get("pinned")))
        self.browser.statusBar().showMessage(f"Oturum açıldı: {name}", 2200)

    def delete_session(self):
        item = self.list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        self.browser.data.setdefault("saved_sessions", {}).pop(name, None)
        self.browser.save()
        self.refresh()


class PrivacyCenterDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Gizlilik Merkezi")
        self.resize(900, 620)
        layout = QVBoxLayout(self)
        title = QLabel("Gizlilik Merkezi")
        title.setObjectName("SettingsTitle")
        layout.addWidget(title)
        desc = QLabel("Geçmiş, önbellek, çerezler ve site izinlerini buradan yönet.")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        self.status = QLabel()
        layout.addWidget(self.status)

        buttons = QVBoxLayout()
        for text, callback in [
            ("Geçmişi Temizle", browser.clear_history_and_report),
            ("Önbelleği Temizle", browser.clear_cache_and_report),
            ("Tüm Site Çerezlerini Temizle", browser.clear_cookies_and_report),
            ("Site İzinlerini Yönet", browser.open_permissions),
            ("Gelişmiş Ayarlar", browser.open_settings),
        ]:
            b = QPushButton(text)
            b.clicked.connect(callback)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        close = QPushButton("Kapat")
        close.clicked.connect(self.accept)
        layout.addStretch(1)
        layout.addWidget(close)
        self.refresh_status()
        try:
            self.setStyleSheet(browser.styleSheet())
        except Exception:
            pass

    def refresh_status(self):
        history_count = len(self.browser.data.get("history", []))
        cookie_text = "hazır"
        self.status.setText(f"Geçmiş: {history_count} kayıt  •  Site çerezleri: {cookie_text}")


class ProfilesDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Profilleri")
        self.resize(820, 560)
        layout = QVBoxLayout(self)
        self.info = QLabel("Her profil kendi Chromium depolamasını kullanır. Google oturumları profiller arasında ayrıdır.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self.switch_selected())
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        add_btn = QPushButton("Yeni Profil")
        add_btn.clicked.connect(self.add_profile)
        switch_btn = QPushButton("Profili Kullan")
        switch_btn.clicked.connect(self.switch_selected)
        delete_btn = QPushButton("Sil")
        delete_btn.clicked.connect(self.delete_profile)
        close_btn = QPushButton("Kapat")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(add_btn)
        buttons.addWidget(switch_btn)
        buttons.addWidget(delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        self.list.clear()
        active = getattr(self.browser, "active_profile_name", "Default")
        for name in _oss_v4_profile_names(self.browser):
            label = f"{name}" + ("  •  AKTİF" if name == active else "")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
        self.list.setCurrentRow(0)

    def add_profile(self):
        name, ok = QInputDialog.getText(self, "Yeni Profil", "Profil adı:")
        name = _oss_v4_safe_name(name)
        if not ok or not name:
            return
        if name in _oss_v4_profile_names(self.browser):
            QMessageBox.information(self, "OSS Browser", "Bu isimde bir profil zaten var.")
            return
        self.browser.data.setdefault("profiles", []).append({"name": name})
        self.browser.save()
        self.refresh()

    def switch_selected(self):
        item = self.list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        _oss_v4_switch_profile(self.browser, name)
        self.accept()

    def delete_profile(self):
        item = self.list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        if name == "Default":
            QMessageBox.information(self, "OSS Browser", "Default profili silinemez.")
            return
        answer = QMessageBox.question(
            self,
            "Profili Sil",
            f"{name} profili silinsin mi? Tarayıcı profil verileri de kullanılmaz hale gelebilir.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.browser.data["profiles"] = [x for x in self.browser.data.get("profiles", []) if x.get("name") != name]
        self.browser.data.setdefault("settings", {})["active_profile"] = "Default"
        self.browser.active_profile_name = "Default"
        self.browser.save()
        self.refresh()


class BookmarkFoldersDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Yer İmi Klasörleri")
        self.resize(700, 500)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        add_btn = QPushButton("Klasör Ekle")
        add_btn.clicked.connect(self.add_folder)
        rename_btn = QPushButton("Yeniden Adlandır")
        rename_btn.clicked.connect(self.rename_folder)
        delete_btn = QPushButton("Sil")
        delete_btn.clicked.connect(self.delete_folder)
        close_btn = QPushButton("Kapat")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(add_btn)
        buttons.addWidget(rename_btn)
        buttons.addWidget(delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for name in self.browser.data.setdefault("bookmark_folders", ["Genel"]):
            self.list.addItem(name)
        if self.list.count():
            self.list.setCurrentRow(0)

    def add_folder(self):
        name, ok = QInputDialog.getText(self, "Yer İmi Klasörü", "Klasör adı:")
        name = _oss_v4_safe_name(name)
        if not ok or not name:
            return
        if name not in self.browser.data["bookmark_folders"]:
            self.browser.data["bookmark_folders"].append(name)
            self.browser.save()
        self.refresh()

    def rename_folder(self):
        item = self.list.currentItem()
        if not item:
            return
        old = item.text()
        if old == "Genel":
            QMessageBox.information(self, "OSS Browser", "Genel klasörü yeniden adlandırılamaz.")
            return
        new, ok = QInputDialog.getText(self, "Yeniden Adlandır", "Yeni ad:", text=old)
        new = _oss_v4_safe_name(new)
        if not ok or not new or new == old:
            return
        folders = self.browser.data.setdefault("bookmark_folders", ["Genel"])
        self.browser.data["bookmark_folders"] = [new if x == old else x for x in folders]
        for bookmark in self.browser.data.get("bookmarks", []):
            if bookmark.get("folder") == old:
                bookmark["folder"] = new
        self.browser.save()
        self.browser.refresh_bookmark_bar()
        self.refresh()

    def delete_folder(self):
        item = self.list.currentItem()
        if not item:
            return
        old = item.text()
        if old == "Genel":
            QMessageBox.information(self, "OSS Browser", "Genel klasörü silinemez.")
            return
        self.browser.data["bookmark_folders"] = [x for x in self.browser.data.get("bookmark_folders", []) if x != old]
        for bookmark in self.browser.data.get("bookmarks", []):
            if bookmark.get("folder") == old:
                bookmark["folder"] = "Genel"
        self.browser.save()
        self.browser.refresh_bookmark_bar()
        self.refresh()


class ThemeCenterDialog(QDialog):
    PRESETS = [
        ("OSS Dark", True, "#7c5cff"),
        ("Midnight Blue", True, "#3b82f6"),
        ("Emerald", True, "#10b981"),
        ("Orange", True, "#f97316"),
        ("Ruby", True, "#ef4444"),
        ("OSS Light", False, "#3b82f6"),
    ]

    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Tema Merkezi")
        self.resize(760, 500)
        layout = QVBoxLayout(self)
        title = QLabel("Tema Merkezi")
        title.setObjectName("SettingsTitle")
        layout.addWidget(title)
        desc = QLabel("Bir tema seç. Değişiklik anında uygulanır ve kaydedilir.")
        layout.addWidget(desc)
        grid = QVBoxLayout()
        for name, dark, accent in self.PRESETS:
            b = QPushButton(f"{name}  •  {accent}")
            b.clicked.connect(lambda _=False, n=name, d=dark, a=accent: self.apply_preset(n, d, a))
            grid.addWidget(b)
        layout.addLayout(grid)
        close = QPushButton("Kapat")
        close.clicked.connect(self.accept)
        layout.addStretch(1)
        layout.addWidget(close)
        try:
            self.setStyleSheet(browser.styleSheet())
        except Exception:
            pass

    def apply_preset(self, name, dark, accent):
        settings = self.browser.data.setdefault("settings", {})
        settings["dark_mode"] = dark
        settings["accent"] = accent
        settings["theme_name"] = name
        self.browser.apply_theme()
        self.browser.save()
        self.browser.statusBar().showMessage(f"Tema uygulandı: {name}", 2200)


# ------------------------------------------------------------
# V4 MainWindow helpers
# ------------------------------------------------------------

def _oss_v4_open_tab_search(self):
    TabSearchDialog(self).exec()


def _oss_v4_open_tab_groups(self):
    TabGroupsDialog(self).exec()


def _oss_v4_open_sessions(self):
    SessionsDialog(self).exec()


def _oss_v4_open_privacy(self):
    PrivacyCenterDialog(self).exec()


def _oss_v4_open_profiles(self):
    ProfilesDialog(self).exec()


def _oss_v4_open_bookmark_folders(self):
    BookmarkFoldersDialog(self).exec()


def _oss_v4_open_theme_center(self):
    ThemeCenterDialog(self).exec()


def _oss_v4_clear_history(self):
    self.data["history"] = []
    self.save()
    self.statusBar().showMessage("Geçmiş temizlendi.", 2000)


def _oss_v4_clear_cache(self):
    try:
        self.browser_profile.clearHttpCache()
        self.statusBar().showMessage("Önbellek temizleme başlatıldı.", 2000)
    except Exception as exc:
        QMessageBox.warning(self, "OSS Browser", f"Önbellek temizlenemedi:\n{exc}")


def _oss_v4_clear_cookies(self):
    try:
        self.browser_profile.cookieStore().deleteAllCookies()
        self.statusBar().showMessage("Çerezlerin silinmesi başlatıldı.", 2500)
    except Exception as exc:
        QMessageBox.warning(self, "OSS Browser", f"Çerezler temizlenemedi:\n{exc}")


def _oss_v4_apply_add_bookmark(self):
    view = self.current_view()
    if not view:
        return
    url = view.url().toString()
    if not is_web_url(url):
        QMessageBox.information(self, "OSS Browser", "Bu sayfa yer imlerine eklenemez.")
        return
    for item in self.data.setdefault("bookmarks", []):
        if item.get("url") == url:
            QMessageBox.information(self, "OSS Browser", "Bu sayfa zaten yer imlerinde.")
            return
    folders = self.data.setdefault("bookmark_folders", ["Genel"])
    if not folders:
        folders.append("Genel")
    folder, ok = QInputDialog.getItem(
        self,
        "Yer İmi Ekle",
        "Klasör:",
        folders,
        0,
        False,
    )
    if not ok:
        return
    title = view.title().strip() or url
    self.data["bookmarks"].insert(0, {"title": title, "url": url, "folder": folder})
    self.save()
    self.refresh_bookmark_bar()
    self.statusBar().showMessage(f"Yer imine eklendi: {folder}", 2200)


def _oss_v4_refresh_bookmark_bar(self):
    if not hasattr(self, "bookmark_layout"):
        return
    while self.bookmark_layout.count():
        item = self.bookmark_layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
    bookmarks = self.data.get("bookmarks", [])
    if not bookmarks:
        empty = QLabel("☆ Yer imleri burada görünecek")
        empty.setObjectName("BookmarkEmpty")
        self.bookmark_layout.addWidget(empty)
    else:
        current_folder = None
        for item in bookmarks:
            folder = item.get("folder", "Genel")
            if folder != current_folder:
                current_folder = folder
                label = QLabel(f" {folder} ")
                label.setObjectName("BookmarkFolderLabel")
                self.bookmark_layout.addWidget(label)
            title = str(item.get("title", item.get("url", "Yer İmi")))
            if len(title) > 28:
                title = title[:28] + "…"
            url = str(item.get("url", ""))
            button = QToolButton()
            button.setObjectName("BookmarkButton")
            button.setText("★ " + title)
            button.setToolTip(f"{folder}\n{url}")
            button.setAutoRaise(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(28)
            button.clicked.connect(lambda u=url: self.new_tab(u))
            self.bookmark_layout.addWidget(button)
    self.bookmark_layout.addStretch(1)


def _oss_v4_set_active_profile(self, name):
    _oss_v4_switch_profile(self, name)


def _oss_v4_setup_feature_menu(self):
    if not hasattr(self, "more_button"):
        return
    menu = self.more_button.menu()
    if menu is None:
        return
    menu.addSeparator()
    v4menu = menu.addMenu("OSS V4 Özellikleri")
    v4menu.addAction("Sekme Ara (Ctrl+Shift+A)", self.open_tab_search)
    v4menu.addAction("Sekme Grupları", self.open_tab_groups)
    v4menu.addAction("Kayıtlı Oturumlar", self.open_sessions)
    v4menu.addAction("Profil Değiştir", self.open_profiles)
    v4menu.addAction("Yer İmi Klasörleri", self.open_bookmark_folders)
    v4menu.addAction("Gizlilik Merkezi", self.open_privacy_center)
    v4menu.addAction("Tema Merkezi", self.open_theme_center)

    action = QAction(self)
    action.setShortcut(QKeySequence("Ctrl+Shift+A"))
    action.triggered.connect(self.open_tab_search)
    self.addAction(action)
    self._oss_v4_menu_ready = True


def _oss_v4_patch_setup_ui(self):
    # This helper is invoked after the original UI is built.
    if getattr(self, "_oss_v4_menu_ready", False):
        return
    _oss_v4_setup_feature_menu(self)


# Bind helpers before MainWindow is instantiated.
MainWindow.open_tab_search = _oss_v4_open_tab_search
MainWindow.open_tab_groups = _oss_v4_open_tab_groups
MainWindow.open_sessions = _oss_v4_open_sessions
MainWindow.open_privacy_center = _oss_v4_open_privacy
MainWindow.open_profiles = _oss_v4_open_profiles
MainWindow.open_bookmark_folders = _oss_v4_open_bookmark_folders
MainWindow.open_theme_center = _oss_v4_open_theme_center
MainWindow.clear_history_and_report = _oss_v4_clear_history
MainWindow.clear_cache_and_report = _oss_v4_clear_cache
MainWindow.clear_cookies_and_report = _oss_v4_clear_cookies
MainWindow._oss_v4_switch_profile = _oss_v4_set_active_profile
MainWindow.get_active_profile = _oss_v4_get_active_profile

# Initialize V4 state before the original setup_ui runs, then append the menu.
_oss_v4_original_setup_ui = MainWindow.setup_ui

def _oss_v4_setup_ui_wrapper(self):
    _oss_v4_init_state(self)
    _oss_v4_original_setup_ui(self)
    _oss_v4_patch_setup_ui(self)

MainWindow.setup_ui = _oss_v4_setup_ui_wrapper

# Add folder-aware bookmarks without removing the existing bookmark storage.
MainWindow.add_bookmark = _oss_v4_apply_add_bookmark
MainWindow.refresh_bookmark_bar = _oss_v4_refresh_bookmark_bar

# Add profile-aware normal pages. (BrowserTab already calls get_active_profile.)

# Advanced download metrics. Existing pause/cancel/folder controls remain intact.
_oss_dw_old_init = DownloadWidget.__init__
_oss_dw_old_update = DownloadWidget.update_progress

def _oss_dw_init_v4(self, request):
    self._oss_start_time = time.time()
    self._oss_last_received = 0
    self._oss_last_time = self._oss_start_time
    _oss_dw_old_init(self, request)


def _oss_dw_update_v4(self):
    _oss_dw_old_update(self)
    try:
        total = int(self.request.totalBytes())
        received = int(self.request.receivedBytes())
        now = time.time()
        elapsed = max(0.001, now - self._oss_start_time)
        speed = received / elapsed
        if speed > 1024 * 1024:
            speed_text = f"{speed / 1024 / 1024:.1f} MB/sn"
        elif speed > 1024:
            speed_text = f"{speed / 1024:.0f} KB/sn"
        else:
            speed_text = f"{speed:.0f} B/sn"
        eta = "—"
        if total > 0 and speed > 0 and received < total:
            remain = max(0, total - received) / speed
            minutes = int(remain // 60)
            seconds = int(remain % 60)
            eta = f"{minutes:02d}:{seconds:02d}"
        if total > 0:
            self.info.setText(
                f"{received / 1024 / 1024:.1f} MB / {total / 1024 / 1024:.1f} MB  •  {speed_text}  •  Kalan {eta}"
            )
        else:
            self.info.setText(f"{received / 1024 / 1024:.1f} MB  •  {speed_text}")
    except Exception:
        pass

DownloadWidget.__init__ = _oss_dw_init_v4
DownloadWidget.update_progress = _oss_dw_update_v4

# Add the new features to the command center without replacing the existing list.
_oss_cc_old_init = CommandCenterDialog.__init__
def _oss_cc_init_v4(self, browser):
    _oss_cc_old_init(self, browser)
    additions = [
        ("Sekme Ara", browser.open_tab_search),
        ("Sekme Grupları", browser.open_tab_groups),
        ("Kayıtlı Oturumlar", browser.open_sessions),
        ("Profil Değiştir", browser.open_profiles),
        ("Yer İmi Klasörleri", browser.open_bookmark_folders),
        ("Gizlilik Merkezi", browser.open_privacy_center),
        ("Tema Merkezi", browser.open_theme_center),
    ]
    self.commands.extend(additions)
    self.refresh()

CommandCenterDialog.__init__ = _oss_cc_init_v4

# Save all V4 state before the original close handler runs.
_oss_main_old_close = MainWindow.closeEvent
def _oss_main_close_v4(self, event):
    try:
        self.save_session()
        self.data.setdefault("settings", {})["active_profile"] = getattr(self, "active_profile_name", "Default")
        self.save()
    except Exception:
        pass
    _oss_main_old_close(self, event)

MainWindow.closeEvent = _oss_main_close_v4


def main():

    app = QApplication(
        sys.argv
    )

    app.setApplicationName(
        APP_NAME
    )

    window = MainWindow()

    window.show()

    sys.exit(
        app.exec()
    )


# ============================================================
# OSS BROWSER V5 - GELİŞMİŞ ÖZELLİKLER
# Performans • Güvenlik • YouTube araçları • AI paneli
# Sekme sesi/grupları • Yedekleme • Site engelleme • Bildirimler
# ============================================================


def _v5_domain(url_text):
    try:
        text = str(url_text or "").strip()
        if not text or text.lower().startswith(("about:", "file:", "data:", "javascript:", "qrc:", "chrome:")):
            return ""
        if "://" not in text:
            text = "https://" + text
        host = (urlparse(text).hostname or "").lower().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


class V5TabGroupsDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Sekme Grupları")
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        for text, cb in [
            ("Yeni Grup", self.save_group),
            ("Siteye Göre Otomatik Grupla", self.auto_group),
            ("Grubu Aç", self.open_group),
            ("Sil", self.delete_group),
            ("Renk", self.change_color),
        ]:
            b = QPushButton(text)
            b.clicked.connect(cb)
            buttons.addWidget(b)
        buttons.addStretch(1)
        close = QPushButton("Kapat")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        self.list.clear()
        groups = self.browser.data.setdefault("tab_groups", {})
        colors = self.browser.data.setdefault("tab_group_colors", {})
        if not groups:
            self.list.addItem("Henüz sekme grubu yok.")
            return
        for name, entries in groups.items():
            color = colors.get(name, "#7c5cff")
            item = QListWidgetItem(f"●  {name}  •  {len(entries)} sekme  •  {color}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def save_group(self):
        name, ok = QInputDialog.getText(self, "Sekme Grubu", "Grup adı:")
        if not ok or not name.strip():
            return
        name = name.strip()[:50]
        self.browser.data.setdefault("tab_groups", {})[name] = _v5_current_tabs(self.browser)
        self.browser.data.setdefault("tab_group_colors", {})[name] = "#7c5cff"
        self.browser.save(); self.refresh()

    def auto_group(self):
        grouped = {}
        for i in range(self.browser.tabs.count()):
            tab = self.browser.tabs.widget(i)
            if not isinstance(tab, BrowserTab) or tab.private:
                continue
            domain = _v5_domain(tab.view.url().toString()) or "Diğer"
            grouped.setdefault(domain, []).append({
                "url": tab.view.url().toString(),
                "pinned": bool(getattr(tab, "pinned", False)),
                "title": tab.view.title().strip(),
            })
        if not grouped:
            QMessageBox.information(self, "OSS Browser", "Gruplanacak açık web sekmesi yok.")
            return
        self.browser.data.setdefault("tab_groups", {}).update(grouped)
        colors = self.browser.data.setdefault("tab_group_colors", {})
        palette = ["#7c5cff", "#3b82f6", "#10b981", "#f97316", "#ef4444", "#eab308"]
        for n, name in enumerate(grouped):
            colors.setdefault(name, palette[n % len(palette)])
        self.browser.save(); self.refresh()

    def open_group(self):
        item = self.list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        for entry in self.browser.data.get("tab_groups", {}).get(name, []):
            if isinstance(entry, dict) and entry.get("url"):
                self.browser.new_tab(entry["url"], private=False, pinned=bool(entry.get("pinned")))
        self.browser.statusBar().showMessage(f"Sekme grubu açıldı: {name}", 2200)

    def delete_group(self):
        item = self.list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        self.browser.data.setdefault("tab_groups", {}).pop(name, None)
        self.browser.data.setdefault("tab_group_colors", {}).pop(name, None)
        self.browser.save(); self.refresh()

    def change_color(self):
        item = self.list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        choices = ["#7c5cff", "#3b82f6", "#10b981", "#f97316", "#ef4444", "#eab308", "#ec4899"]
        color, ok = QInputDialog.getItem(self, "Grup Rengi", "Renk:", choices, 0, False)
        if ok:
            self.browser.data.setdefault("tab_group_colors", {})[name] = color
            self.browser.save(); self.refresh()


def _v5_current_tabs(browser):
    out = []
    for i in range(browser.tabs.count()):
        tab = browser.tabs.widget(i)
        if isinstance(tab, BrowserTab) and not tab.private:
            url = tab.view.url().toString()
            if url and not url.startswith("about:") and url != HOME_URL:
                out.append({"url": url, "pinned": bool(getattr(tab, "pinned", False)), "title": tab.view.title().strip()})
    return out[:40]


class V5SecurityDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Güvenlik Merkezi")
        self.resize(940, 670)
        self.setMinimumSize(780, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        heading = QHBoxLayout()
        icon_label = QLabel("✓")
        icon_label.setObjectName("SecurityIcon")
        icon_label.setFixedSize(50, 50)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_box = QVBoxLayout()
        title = QLabel("Güvenlik Merkezi")
        title.setObjectName("SecurityTitle")
        subtitle = QLabel("Site engellerini, açılır pencereleri ve indirme uyarılarını yönetin.")
        subtitle.setObjectName("SecurityMuted")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        heading.addWidget(icon_label)
        heading.addLayout(title_box, 1)
        root.addLayout(heading)

        self.url_label = QLabel()
        self.url_label.setObjectName("SecurityCurrent")
        self.url_label.setWordWrap(True)
        root.addWidget(self.url_label)

        checks = QWidget()
        checks_layout = QVBoxLayout(checks)
        checks_layout.setContentsMargins(14, 10, 14, 10)
        checks_layout.setSpacing(3)
        checks.setObjectName("SecurityPanel")
        self.popup_check = QCheckBox("Açılır pencereleri engelle")
        self.popup_check.setChecked(bool(browser.data.get("settings", {}).get("block_popups", True)))
        self.warning_check = QCheckBox("Şüpheli indirmelerde uyar")
        self.warning_check.setChecked(bool(browser.data.get("settings", {}).get("warn_downloads", True)))
        checks_layout.addWidget(self.popup_check)
        checks_layout.addWidget(self.warning_check)
        root.addWidget(checks)

        list_header = QHBoxLayout()
        list_title = QLabel("Engellenen siteler")
        list_title.setObjectName("SecuritySectionTitle")
        self.block_count = QLabel("0 site")
        self.block_count.setObjectName("SecurityCount")
        list_header.addWidget(list_title)
        list_header.addStretch(1)
        list_header.addWidget(self.block_count)
        root.addLayout(list_header)

        self.blocked = QListWidget()
        self.blocked.setObjectName("BlockedSitesList")
        self.blocked.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.blocked.itemSelectionChanged.connect(self._selection_changed)
        self.blocked.itemDoubleClicked.connect(lambda _item: self.unblock_current())
        root.addWidget(self.blocked, 1)

        buttons = QHBoxLayout()
        self.block_button = QPushButton("Mevcut siteyi engelle")
        self.unblock_button = QPushButton("Seçili engeli kaldır")
        self.unblock_button.setObjectName("SecondaryButton")
        self.clear_all_button = QPushButton("Tüm engelleri kaldır")
        self.clear_all_button.setObjectName("DangerButton")
        self.clear_cookies_button = QPushButton("Mevcut sitenin çerezlerini temizle")
        self.clear_cookies_button.setObjectName("SecondaryButton")
        buttons.addWidget(self.block_button)
        buttons.addWidget(self.unblock_button)
        buttons.addWidget(self.clear_all_button)
        root.addLayout(buttons)
        root.addWidget(self.clear_cookies_button)

        footer = QHBoxLayout()
        footer.addStretch(1)
        save = QPushButton("Kaydet")
        close = QPushButton("Kapat")
        close.setObjectName("SecondaryButton")
        footer.addWidget(save)
        footer.addWidget(close)
        root.addLayout(footer)

        self.block_button.clicked.connect(self.block_current)
        self.unblock_button.clicked.connect(self.unblock_current)
        self.clear_all_button.clicked.connect(self.unblock_all)
        self.clear_cookies_button.clicked.connect(self.clear_current_site)
        save.clicked.connect(self.save)
        close.clicked.connect(self.accept)

        self.setStyleSheet("""
            QDialog { background:#0b1018; color:#edf2fb; }
            QLabel { color:#edf2fb; }
            QLabel#SecurityIcon { background:#211b3e; border:1px solid #4d3d82; border-radius:15px; color:#b9a8ff; font-size:24px; font-weight:900; }
            QLabel#SecurityTitle { font-size:25px; font-weight:800; }
            QLabel#SecurityMuted { color:#92a0b6; font-size:12px; }
            QLabel#SecurityCurrent { background:#111a28; border:1px solid #253248; border-radius:12px; padding:13px 15px; color:#cbd6e8; }
            QWidget#SecurityPanel { background:#111a28; border:1px solid #253248; border-radius:12px; }
            QLabel#SecuritySectionTitle { font-size:15px; font-weight:750; }
            QLabel#SecurityCount { color:#9daac0; background:#172235; border-radius:10px; padding:5px 10px; }
            QListWidget#BlockedSitesList { background:#0e1520; border:1px solid #253248; border-radius:12px; padding:8px; color:#dce5f4; }
            QListWidget#BlockedSitesList::item { padding:11px 12px; margin:2px; border-radius:8px; }
            QListWidget#BlockedSitesList::item:selected { background:#34285f; color:white; }
            QCheckBox { padding:7px 3px; color:#dbe4f2; }
            QPushButton { background:#7757ed; border:0; border-radius:9px; padding:10px 14px; color:white; font-weight:700; }
            QPushButton:hover { background:#8a70f5; }
            QPushButton#SecondaryButton { background:#1a2637; border:1px solid #304057; color:#dce5f4; }
            QPushButton#SecondaryButton:hover { background:#24344a; }
            QPushButton#DangerButton { background:#44232b; border:1px solid #70323d; color:#ffcad0; }
            QPushButton#DangerButton:hover { background:#5b2934; }
        """)
        self.refresh()

    def _selected_host(self):
        item = self.blocked.currentItem()
        if not item:
            return ""
        value = item.data(Qt.ItemDataRole.UserRole)
        return _v5_domain(str(value or item.text()))

    def _selection_changed(self):
        selected = bool(self._selected_host())
        self.unblock_button.setEnabled(selected or bool(getattr(self, "_current_host", "")))

    def refresh(self):
        view = self.browser.current_view()
        url = view.url().toString() if view else ""
        host = _v5_domain(url)
        self._current_host = host
        if host:
            scheme = urlparse(url).scheme.upper() or "WEB"
            self.url_label.setText(f"Açık sekme: {host}   ·   Bağlantı: {scheme}\nTam adres: {url}")
        else:
            self.url_label.setText(f"Açık sekmede bilinen bir site yok.\nAdres: {url or 'Yeni sekme'}")
        previous = self._selected_host()
        self.blocked.clear()
        cleaned = sorted({_v5_domain(item) for item in self.browser.data.setdefault("blocked_sites", []) if _v5_domain(item)})
        for host_name in cleaned:
            item = QListWidgetItem("⛔   " + host_name)
            item.setData(Qt.ItemDataRole.UserRole, host_name)
            self.blocked.addItem(item)
            if host_name == previous:
                self.blocked.setCurrentItem(item)
        self.block_count.setText(f"{len(cleaned)} site")
        self.block_button.setEnabled(bool(host) and host not in cleaned)
        self.unblock_button.setEnabled(bool(self._selected_host()) or bool(host and host in cleaned))
        self.clear_all_button.setEnabled(bool(cleaned))

    def _sync_blocker(self):
        try:
            self.browser.ad_blocker.blocked_sites = {
                _v5_domain(item) for item in self.browser.data.get("blocked_sites", []) if _v5_domain(item)
            }
        except Exception:
            pass

    def block_current(self):
        host = _v5_domain(getattr(self, "_current_host", ""))
        if not host:
            QMessageBox.information(self, "OSS Güvenlik Merkezi", "Önce engellemek istediğin siteyi aç.")
            return
        blocked = self.browser.data.setdefault("blocked_sites", [])
        if host not in {_v5_domain(item) for item in blocked}:
            blocked.append(host)
        self._sync_blocker()
        self.browser.save()
        self.refresh()
        self.browser.statusBar().showMessage(host + " engellendi.", 2500)

    def unblock_current(self):
        host = self._selected_host() or _v5_domain(getattr(self, "_current_host", ""))
        if not host:
            QMessageBox.information(self, "OSS Güvenlik Merkezi", "Listeden engelli bir site seç.")
            return
        view = self.browser.current_view()
        current_url = view.url().toString() if view else ""
        old = self.browser.data.setdefault("blocked_sites", [])
        self.browser.data["blocked_sites"] = [item for item in old if _v5_domain(item) != host]
        self._sync_blocker()
        self.browser.save()
        self.refresh()
        self.browser.statusBar().showMessage(host + " engeli kaldırıldı.", 2500)
        # Engellenmiş sayfa halen açıksa yeniden yükle; açık sekme about:blank ise
        # az önce engeli kaldırılan siteyi hemen açarak kullanıcıyı uğraştırma.
        if view and current_url.startswith(("http://", "https://")) and _v5_domain(current_url) == host:
            QTimer.singleShot(0, lambda v=view, u=current_url: v.setUrl(QUrl(u)))
        elif view and (not current_url or current_url.startswith("about:")):
            QTimer.singleShot(0, lambda v=view, u=host: v.setUrl(QUrl("https://" + u)))

    def unblock_all(self):
        blocked = self.browser.data.setdefault("blocked_sites", [])
        if not blocked:
            return
        answer = QMessageBox.question(
            self, "Tüm site engelleri", "Listedeki bütün site engelleri kaldırılsın mı?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.browser.data["blocked_sites"] = []
        self._sync_blocker()
        self.browser.save()
        self.refresh()
        self.browser.statusBar().showMessage("Tüm site engelleri kaldırıldı.", 2500)

    def clear_current_site(self):
        self.browser.clear_current_site_cookies()
        self.refresh()

    def save(self):
        settings = self.browser.data.setdefault("settings", {})
        settings["block_popups"] = self.popup_check.isChecked()
        settings["warn_downloads"] = self.warning_check.isChecked()
        self._sync_blocker()
        self.browser.save()
        self.browser.statusBar().showMessage("Güvenlik ayarları kaydedildi.", 2200)


class V5PerformanceDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Performans Merkezi")
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.info)
        settings = browser.data.setdefault("settings", {})
        self.sleep_check = QCheckBox("Uzun süre kullanılmayan sekmeleri uyut")
        self.sleep_check.setChecked(bool(settings.get("sleep_inactive_tabs", True)))
        self.sleep_spin = QSpinBox(); self.sleep_spin.setRange(20, 600); self.sleep_spin.setSuffix(" sn")
        self.sleep_spin.setValue(int(settings.get("sleep_after_seconds", 90)))
        self.gpu_check = QCheckBox("Donanım hızlandırmayı kullan (yeniden başlatma gerekir)")
        self.gpu_check.setChecked(bool(settings.get("hardware_acceleration", True)))
        layout.addWidget(self.sleep_check)
        layout.addWidget(self._row("Uyutma süresi", self.sleep_spin))
        layout.addWidget(self.gpu_check)
        buttons = QHBoxLayout()
        now = QPushButton("Pasif Sekmeleri Şimdi Uyut")
        wake = QPushButton("Tüm Sekmeleri Uyandır")
        close = QPushButton("Kapat")
        now.clicked.connect(browser.sleep_inactive_tabs)
        wake.clicked.connect(browser.wake_all_tabs)
        close.clicked.connect(self.accept)
        buttons.addWidget(now); buttons.addWidget(wake); buttons.addStretch(1); buttons.addWidget(close)
        layout.addLayout(buttons)
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(1200)
        self.refresh()

    def _row(self, text, widget):
        box = QWidget(); lay = QHBoxLayout(box); lay.addWidget(QLabel(text)); lay.addStretch(1); lay.addWidget(widget); return box

    def refresh(self):
        settings = self.browser.data.setdefault("settings", {})
        settings["sleep_inactive_tabs"] = self.sleep_check.isChecked()
        settings["sleep_after_seconds"] = self.sleep_spin.value()
        settings["hardware_acceleration"] = self.gpu_check.isChecked()
        lines = [
            f"Sekme sayısı: {self.browser.tabs.count()}",
            f"Aktif profil: {getattr(self.browser, 'active_profile_name', 'Default')}",
        ]
        if psutil:
            vm = psutil.virtual_memory(); net = psutil.net_io_counters()
            lines += [f"RAM: {vm.percent:.1f}%  •  {vm.used / 1024**3:.2f} / {vm.total / 1024**3:.2f} GB", f"Ağ toplamı: ↑ {net.bytes_sent / 1024**2:.0f} MB  ↓ {net.bytes_recv / 1024**2:.0f} MB"]
        else:
            lines.append("RAM/Ağ ölçümü için psutil kurulu değil.")
        self.info.setText("\n".join(lines))

    def closeEvent(self, event):
        self.browser.data.setdefault("settings", {})["sleep_inactive_tabs"] = self.sleep_check.isChecked()
        self.browser.data["settings"]["sleep_after_seconds"] = self.sleep_spin.value()
        self.browser.data["settings"]["hardware_acceleration"] = self.gpu_check.isChecked()
        self.browser.save(); event.accept()


class V5YouTubeDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS YouTube Araçları")
        self.resize(900, 620)
        layout = QVBoxLayout(self)
        self.rate = QComboBox(); self.rate.addItems(["0.25x", "0.5x", "0.75x", "1x", "1.25x", "1.5x", "1.75x", "2x"]); self.rate.setCurrentText("1x")
        row = QHBoxLayout(); row.addWidget(QLabel("Hız:")); row.addWidget(self.rate); row.addStretch(1); layout.addLayout(row)
        buttons = QHBoxLayout()
        for text, js in [
            ("Kalite: 1080p", "quality('hd1080')"),
            ("Kalite: 720p", "quality('hd720')"),
            ("Kalite: 480p", "quality('large')"),
            ("Otomatik kalite", "quality('auto')"),
            ("Sinema modu", "theater()"),
            ("Mini oynatıcı", "mini()"),
            ("Shorts gizle", "shorts()"),
        ]:
            b = QPushButton(text); b.clicked.connect(lambda _=False, code=js: self.run_yt(code)); buttons.addWidget(b)
        layout.addLayout(buttons)
        shot = QPushButton("Video / sayfa ekran görüntüsü"); shot.clicked.connect(browser.save_screenshot); layout.addWidget(shot)
        add = QPushButton("Geçerli videoyu yerel YouTube listesine ekle"); add.clicked.connect(self.add_playlist); layout.addWidget(add)
        open_pl = QPushButton("Yerel YouTube listemi aç"); open_pl.clicked.connect(self.open_playlist); layout.addWidget(open_pl)
        self.status = QLabel("YouTube sayfasında kullan."); self.status.setWordWrap(True); layout.addWidget(self.status)
        layout.addStretch(1)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); layout.addWidget(close)

    def run_yt(self, action):
        view = self.browser.current_view()
        if not view:
            return
        rate = self.rate.currentText().replace("x", "")
        js = f"""
        (()=>{{
          const r={rate};
          const video=document.querySelector('video');
          function quality(q){{
            try{{
              const btn=[...document.querySelectorAll('.ytp-settings-button')][0];
              if(btn) btn.click();
              setTimeout(()=>{{
                const texts=[...document.querySelectorAll('.ytp-menuitem')];
                const target=texts.find(x=>/Kalite|Quality/i.test(x.innerText||''));
                if(target){{ target.click(); setTimeout(()=>{{
                    const item=[...document.querySelectorAll('.ytp-menuitem')].find(x=>new RegExp(q,'i').test(x.innerText||'') || (q==='auto' && /Auto|Otomatik/i.test(x.innerText||'')) );
                    if(item) item.click();
                }},150); }}
              }},150);
            }}catch(e){{}}
          }}
          function theater(){{ const b=document.querySelector('.ytp-size-button'); if(b) b.click(); }}
          function mini(){{ const b=document.querySelector('.ytp-miniplayer-button'); if(b) b.click(); }}
          function shorts(){{ document.querySelectorAll('ytd-reel-shelf-renderer, a[href^="/shorts/"]').forEach(e=>{{const x=e.closest('ytd-rich-item-renderer')||e; if(x) x.remove();}}); }}
          video && (video.playbackRate=r);
          {action}
        }})();
        """
        view.page().runJavaScript(js)
        self.status.setText("YouTube komutu uygulandı.")

    def add_playlist(self):
        view = self.browser.current_view()
        if not view: return
        url = view.url().toString()
        if 'youtube.com/' not in url and 'youtu.be/' not in url:
            QMessageBox.information(self, "OSS Browser", "Bu sayfa bir YouTube videosu değil."); return
        title = view.title().strip() or url
        items = self.browser.data.setdefault("youtube_playlist", [])
        if not any(x.get("url") == url for x in items):
            items.append({"title": title, "url": url})
            self.browser.save()
        self.status.setText("Video yerel YouTube listesine eklendi.")

    def open_playlist(self):
        dlg = QDialog(self); dlg.setWindowTitle("OSS YouTube Listem"); dlg.resize(700, 500)
        lay=QVBoxLayout(dlg); lst=QListWidget(); lay.addWidget(lst)
        for item in self.browser.data.get("youtube_playlist", []):
            row=QListWidgetItem(item.get("title") or item.get("url")); row.setData(Qt.ItemDataRole.UserRole, item.get("url")); lst.addItem(row)
        lst.itemDoubleClicked.connect(lambda item: (self.browser.new_tab(item.data(Qt.ItemDataRole.UserRole)), dlg.accept()))
        c=QPushButton("Kapat"); c.clicked.connect(dlg.accept); lay.addWidget(c); dlg.exec()


class V5BackupDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser=browser; self.setWindowTitle("OSS Yedekleme ve Senkronizasyon"); self.resize(760,520)
        lay=QVBoxLayout(self); info=QLabel("Ayarlar, yer imleri, geçmiş, kayıtlı oturumlar, sekme grupları ve profil listesini tek JSON dosyasında yedekleyebilirsin."); info.setWordWrap(True); lay.addWidget(info)
        exp=QPushButton("Yedek Dışa Aktar"); imp=QPushButton("Yedekten İçe Aktar"); backup_open=QPushButton("Açık Sekmeleri Yedekle")
        exp.clicked.connect(self.export_backup); imp.clicked.connect(self.import_backup); backup_open.clicked.connect(self.export_open_tabs)
        lay.addWidget(exp); lay.addWidget(imp); lay.addWidget(backup_open); lay.addStretch(1); c=QPushButton("Kapat"); c.clicked.connect(self.accept); lay.addWidget(c)

    def payload(self):
        keys=("settings","bookmarks","history","session_tabs","saved_sessions","tab_groups","tab_group_colors","bookmark_folders","profiles","youtube_playlist","notes","workspaces","nova_custom_sources")
        return {k:self.browser.data.get(k) for k in keys}

    def export_backup(self):
        path,_=QFileDialog.getSaveFileName(self,"OSS yedeği",str(APP_DIR/"oss_backup.json"),"JSON (*.json)")
        if not path:return
        Path(path).write_text(json.dumps({"version":5,"created":datetime.now().isoformat(),"data":self.payload()},ensure_ascii=False,indent=2),encoding="utf-8")
        QMessageBox.information(self,"OSS Browser","Yedek oluşturuldu.")

    def export_open_tabs(self):
        path,_=QFileDialog.getSaveFileName(self,"Açık sekmeler",str(APP_DIR/"oss_tabs.json"),"JSON (*.json)")
        if not path:return
        Path(path).write_text(json.dumps(_v5_current_tabs(self.browser),ensure_ascii=False,indent=2),encoding="utf-8")
        QMessageBox.information(self,"OSS Browser","Açık sekmeler yedeklendi.")

    def import_backup(self):
        path,_=QFileDialog.getOpenFileName(self,"OSS yedeği seç",str(APP_DIR),"JSON (*.json)")
        if not path:return
        try:
            obj=json.loads(Path(path).read_text(encoding="utf-8")); data=obj.get("data",obj)
            if not isinstance(data,dict): raise ValueError("Geçersiz yedek")
            for key in ("settings","bookmarks","history","session_tabs","saved_sessions","tab_groups","tab_group_colors","bookmark_folders","profiles","youtube_playlist","notes","workspaces","nova_custom_sources"):
                if key in data: self.browser.data[key]=data[key]
            self.browser.data.setdefault("bookmark_folders",["Genel"]); self.browser.save(); self.browser.refresh_bookmark_bar(); QMessageBox.information(self,"OSS Browser","Yedek içe aktarıldı. Bazı ayarlar için yeniden başlatma gerekebilir.")
        except Exception as exc:
            QMessageBox.warning(self,"OSS Browser",f"Yedek alınamadı:\n{exc}")


class V5AIPanel(QDockWidget):
    def __init__(self, browser):
        super().__init__("OSS AI", browser)
        self.browser=browser; self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea|Qt.DockWidgetArea.LeftDockWidgetArea)
        host=QWidget(); lay=QVBoxLayout(host)
        title=QLabel("OSS AI Yardımcı"); title.setObjectName("SettingsTitle"); lay.addWidget(title)
        self.output=QTextBrowser(); lay.addWidget(self.output,1)
        buttons=QHBoxLayout()
        for text,cb in [("Metni Al",self.extract),("Özetle",self.summarize),("Çevir",self.translate)]:
            b=QPushButton(text); b.clicked.connect(cb); buttons.addWidget(b)
        lay.addLayout(buttons); self.setWidget(host); self.extract()

    def extract(self):
        view=self.browser.current_view()
        if not view:return
        view.page().runJavaScript("document.title+'\\n\\n'+(document.body?.innerText||'').slice(0,24000)", lambda t:self._show("Sayfa metni", t or "Metin alınamadı."))

    def _show(self, title, text):
        self.output.setPlainText(f"{title}\n\n{str(text)[:24000]}")

    def summarize(self):
        view=self.browser.current_view()
        if not view:return
        view.page().runJavaScript("(document.body?.innerText||'').slice(0,30000)", self._summarize_text)

    def _summarize_text(self, text):
        if not text: self._show("Özet","Metin bulunamadı."); return
        clean=re.sub(r'\s+',' ',str(text)).strip()
        parts=re.split(r'(?<=[.!?])\s+',clean)
        summary=' '.join(parts[:6])
        self._show("OSS AI — Yerel Özet", summary if summary else clean[:1200])

    def translate(self):
        view=self.browser.current_view()
        if not view:return
        # Çeviri işlemini güvenilir şekilde Google Translate'e bırakır; mevcut sayfayı bozmaz.
        url=view.url().toString()
        self.browser.new_tab("https://translate.google.com/translate?sl=auto&tl=tr&u="+quote_plus(url))


class V5PerformanceBadge(QLabel):
    pass


class V5AdvancedCenter(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser=browser; self.setWindowTitle("OSS Gelişmiş Merkezi"); self.resize(960,680)
        lay=QVBoxLayout(self); self.tabs=QTabWidget(); lay.addWidget(self.tabs)
        # Performans
        p=QWidget(); pl=QVBoxLayout(p); self.perf_label=QLabel(); self.perf_label.setWordWrap(True); pl.addWidget(self.perf_label)
        sleep=QPushButton("Pasif Sekmeleri Uyut"); wake=QPushButton("Tüm Sekmeleri Uyandır"); pl.addWidget(sleep); pl.addWidget(wake); sleep.clicked.connect(browser.sleep_inactive_tabs); wake.clicked.connect(browser.wake_all_tabs)
        self.tabs.addTab(p,"Performans")
        # Güvenlik
        s=QWidget(); sl=QVBoxLayout(s); btn=QPushButton("Güvenlik Merkezi"); btn.clicked.connect(lambda: V5SecurityDialog(browser).exec()); sl.addWidget(btn); block=QPushButton("Mevcut siteyi engelle/engel kaldır"); block.clicked.connect(browser.toggle_current_site_block); sl.addWidget(block); sl.addStretch(1); self.tabs.addTab(s,"Güvenlik")
        # YouTube
        y=QWidget(); yl=QVBoxLayout(y); yt=QPushButton("YouTube Araçlarını Aç"); yt.clicked.connect(lambda: V5YouTubeDialog(browser).exec()); yl.addWidget(yt); yl.addWidget(QLabel("Kalite, hız, sinema, mini oynatıcı, Shorts ve yerel liste araçları.")); yl.addStretch(1); self.tabs.addTab(y,"YouTube")
        # Yedek
        b=QWidget(); bl=QVBoxLayout(b); bk=QPushButton("Yedekleme / Senkronizasyon"); bk.clicked.connect(lambda: V5BackupDialog(browser).exec()); bl.addWidget(bk); bl.addStretch(1); self.tabs.addTab(b,"Yedekleme")
        # AI
        a=QWidget(); al=QVBoxLayout(a); ap=QPushButton("OSS AI panelini aç"); ap.clicked.connect(browser.toggle_ai_panel); al.addWidget(ap); al.addWidget(QLabel("Sayfadan metin alma, yerel özet ve çeviri araçları.")); al.addStretch(1); self.tabs.addTab(a,"AI")
        close=QPushButton("Kapat"); close.clicked.connect(self.accept); lay.addWidget(close)
        self.timer=QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(1000); self.refresh()

    def refresh(self):
        if psutil:
            vm=psutil.virtual_memory(); cpu=psutil.cpu_percent(interval=None); disk=psutil.disk_usage(str(Path.home().anchor or '/'))
            self.perf_label.setText(f"CPU: {cpu:.0f}%\nRAM: {vm.percent:.1f}% ({vm.used/1024**3:.2f}/{vm.total/1024**3:.2f} GB)\nDisk: {disk.percent:.0f}%\nAçık sekmeler: {self.browser.tabs.count()}")
        else:
            self.perf_label.setText(f"Açık sekmeler: {self.browser.tabs.count()}\npsutil kurulu değil.")


# ------------------------------------------------------------
# V5 state helpers and safe overlays
# ------------------------------------------------------------

def _v5_update_security_badge(browser):
    if not hasattr(browser, 'security_badge'): return
    view=browser.current_view()
    url=view.url().toString() if view else ''
    if url.startswith('https://'):
        browser.security_badge.setText('🔒 HTTPS')
    elif url.startswith('http://'):
        browser.security_badge.setText('⚠ HTTP')
    else:
        browser.security_badge.setText('•')


def _v5_get_page_title(tab):
    return tab.view.title().strip() or "Yeni Sekme"


def _v5_toggle_site_block(browser, host=None):
    view = browser.current_view()
    url = view.url().toString() if view else ""
    host = _v5_domain(host or url)
    if not host:
        browser.statusBar().showMessage("Engellenecek site adresi bulunamadı.", 2200)
        return
    blocked = browser.data.setdefault("blocked_sites", [])
    canonical = {_v5_domain(item) for item in blocked}
    if host in canonical:
        browser.data["blocked_sites"] = [item for item in blocked if _v5_domain(item) != host]
        msg = f"{host} engeli kaldırıldı."
    else:
        blocked.append(host)
        msg = f"{host} engellendi."
    try:
        browser.ad_blocker.blocked_sites = {_v5_domain(item) for item in browser.data.get("blocked_sites", []) if _v5_domain(item)}
    except Exception:
        pass
    browser.save()
    browser.statusBar().showMessage(msg, 2200)


def _v5_clear_current_site_cookies(browser):
    view=browser.current_view(); url=view.url().toString() if view else ''
    host=_v5_domain(url)
    if not host:
        return
    try:
        store=browser.get_active_profile().cookieStore()
        cookies=[]
        def added(cookie):
            try:
                if host in cookie.domain().lower().lstrip('.'):
                    cookies.append(cookie)
            except Exception: pass
        store.cookieAdded.connect(added)
        def done():
            try:
                for c in cookies: store.deleteCookie(c)
                store.cookieAdded.disconnect(added)
            except Exception: pass
            browser.statusBar().showMessage(host+" site çerezleri temizleme başlatıldı.",2500)
        QTimer.singleShot(1200, done)
        store.loadAllCookies()
    except Exception as exc:
        browser.statusBar().showMessage(f"Çerez temizlenemedi: {exc}",2500)


def _v5_sleep_inactive(browser):
    if not psutil and False: return
    now=time.monotonic(); current=browser.current_tab(); seconds=int(browser.data.get('settings',{}).get('sleep_after_seconds',90))
    for i in range(browser.tabs.count()):
        tab=browser.tabs.widget(i)
        if not isinstance(tab,BrowserTab) or tab is current or tab.private or getattr(tab,'pinned',False):
            continue
        if getattr(tab,'_v5_last_active',now)+seconds > now: continue
        page=tab.view.page()
        try:
            if hasattr(page,'isPlayingAudio') and page.isPlayingAudio(): continue
        except Exception: pass
        try:
            state=getattr(QWebEnginePage,'LifecycleState',None)
            frozen=getattr(state,'Frozen',None) if state else None
            if frozen is not None: page.setLifecycleState(frozen)
        except Exception: pass


def _v5_wake_all(browser):
    for i in range(browser.tabs.count()):
        tab=browser.tabs.widget(i)
        if isinstance(tab,BrowserTab):
            try:
                state=getattr(QWebEnginePage,'LifecycleState',None); active=getattr(state,'Active',None) if state else None
                if active is not None: tab.view.page().setLifecycleState(active)
            except Exception: pass
            tab._v5_last_active=time.monotonic()


def _v5_toggle_ai(browser):
    dock=getattr(browser,'ai_dock',None)
    if dock is None:
        dock=V5AIPanel(browser); browser.ai_dock=dock; browser.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,dock)
    dock.setVisible(not dock.isVisible())
    if dock.isVisible(): dock.extract()


def _v5_show_advanced(browser):
    V5AdvancedCenter(browser).exec()


def _v5_open_performance(browser):
    V5PerformanceDialog(browser).exec()


def _v5_open_youtube(browser):
    V5YouTubeDialog(browser).exec()


def _v5_open_backup(browser):
    V5BackupDialog(browser).exec()


def _v5_patch_context_menu(self, position):
    index=self.browser.tabs.tabBar().tabAt(position) if hasattr(self,'browser') else -1
    if index < 0: return
    # Preserve the old context menu's core behavior while adding V5 controls.
    menu=QMenu(self)
    back=menu.addAction('← Geri'); forward=menu.addAction('→ İleri'); reload=menu.addAction('⟳ Yenile')
    menu.addSeparator()
    new_tab=menu.addAction('Yeni sekmede aç'); copy_link=menu.addAction('Adresini kopyala')
    tab=self.browser.tabs.widget(index)
    menu.addSeparator()
    muted=False
    try: muted=bool(tab.view.page().isAudioMuted())
    except Exception: pass
    mute=menu.addAction('Sesi Aç' if muted else 'Sesi Kapat')
    pin=menu.addAction('Sabitlemeyi Kaldır' if getattr(tab,'pinned',False) else 'Sekmeyi Sabitle')
    group=menu.addAction('Sekme Grupları')
    menu.addSeparator(); close=menu.addAction('Sekmeyi Kapat'); dup=menu.addAction('Sekmeyi Çoğalt')
    action=menu.exec(self.view.mapToGlobal(position))
    if action==back:self.view.back()
    elif action==forward:self.view.forward()
    elif action==reload:self.view.reload()
    elif action==new_tab:
        u=self.view.url().toString();
        if u:self.browser.new_tab(u)
    elif action==copy_link: QApplication.clipboard().setText(self.view.url().toString())
    elif action==mute:
        try: tab.view.page().setAudioMuted(not muted)
        except Exception: pass
    elif action==pin:self.browser.toggle_pin_tab(index)
    elif action==group:self.browser.open_tab_groups()
    elif action==close:self.browser.close_tab(index)
    elif action==dup:self.browser.new_tab(self.view.url().toString(), getattr(tab,'private',False))


def _v5_patch_browser_tab_init():
    old=BrowserTab.__init__
    if getattr(BrowserTab,'_v5_wrapped',False): return
    def wrapped(self, browser, private=False):
        old(self,browser,private)
        self._v5_last_active=time.monotonic()
        try:
            self.view.page().audibleChanged.connect(lambda audible, t=self: browser.tab_audio_state_changed(t, audible))
        except Exception: pass
        try:
            self.view.loadStarted.connect(lambda t=self: setattr(t,'_v5_load_start',time.monotonic()))
        except Exception: pass
        try:
            self.view.loadFinished.connect(lambda ok, t=self: browser.page_load_metric(t, ok))
        except Exception: pass
    BrowserTab.__init__=wrapped
    BrowserTab._v5_wrapped=True


# Wrap MainWindow methods while preserving existing behavior.
_v5_old_setup_ui=MainWindow.setup_ui
_v5_old_current_changed=MainWindow.current_tab_changed
_v5_old_tab_url=MainWindow.tab_url_changed
_v5_old_download=MainWindow.download_requested
_v5_old_tab_title=MainWindow.tab_title_changed
_v5_old_save=MainWindow.save
_v5_old_close=MainWindow.closeEvent


def _v5_setup_ui(self):
    _v5_old_setup_ui(self)
    # Security badge at the right edge of the address toolbar.
    try:
        self.security_badge=QToolButton(); self.security_badge.setAutoRaise(True); self.security_badge.setText('•'); self.navigation_toolbar.addWidget(self.security_badge)
        self.security_badge.setToolTip('Site güvenliği / HTTPS durumu'); self.security_badge.clicked.connect(lambda: V5SecurityDialog(self).exec())
    except Exception: pass
    # Performance badge on status bar.
    self.performance_badge=QLabel('CPU —  RAM —'); self.statusBar().addPermanentWidget(self.performance_badge)
    # Add V5 items to existing menu without replacing old menu.
    menu=self.more_button.menu()
    if menu is not None:
        menu.addSeparator()
        v5=menu.addMenu('OSS V5 / Gelişmiş')
        v5.addAction('Gelişmiş Merkez',lambda: _v5_show_advanced(self))
        v5.addAction('Performans Merkezi',lambda: _v5_open_performance(self))
        v5.addAction('Güvenlik Merkezi',lambda: V5SecurityDialog(self).exec())
        v5.addAction('YouTube Araçları',lambda: _v5_open_youtube(self))
        v5.addAction('OSS AI Paneli',lambda: _v5_toggle_ai(self))
        v5.addAction('Yedekleme / Senkronizasyon',lambda: _v5_open_backup(self))
        v5.addAction('Siteyi Engelle / Engel Kaldır',lambda: self.toggle_current_site_block())
        v5.addAction('Tüm Sekmeleri Uyandır',lambda: self.wake_all_tabs())
    # Additional shortcuts
    QShortcut = None


def _v5_current_changed(self,index):
    tab=self.tabs.widget(index) if 0<=index<self.tabs.count() else None
    if isinstance(tab,BrowserTab):
        tab._v5_last_active=time.monotonic()
        try:
            state=getattr(QWebEnginePage,'LifecycleState',None); active=getattr(state,'Active',None) if state else None
            if active is not None: tab.view.page().setLifecycleState(active)
        except Exception: pass
    _v5_old_current_changed(self,index)
    _v5_update_security_badge(self)


def _v5_tab_url(self,tab,url):
    _v5_old_tab_url(self,tab,url); _v5_update_security_badge(self)


def _v5_download(self,request):
    filename=(request.downloadFileName() or 'indirilen_dosya')
    dangerous={'.exe','.scr','.bat','.cmd','.com','.msi','.ps1','.vbs','.js','.jar','.dll'}
    warn=bool(self.data.get('settings',{}).get('warn_downloads',True))
    if warn and Path(filename).suffix.lower() in dangerous:
        ans=QMessageBox.question(self,'OSS Güvenlik',f'Bu dosya çalıştırılabilir bir dosya:\n\n{filename}\n\nİndirmeye devam edilsin mi?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if ans!=QMessageBox.StandardButton.Yes:
            request.cancel(); return
    _v5_old_download(self,request)


def _v5_tab_title(self,tab,title):
    if getattr(tab,'_v5_audio_muted',False):
        title='🔇 '+title
    elif getattr(tab,'_v5_audio',False):
        title='🔊 '+title
    _v5_old_tab_title(self,tab,title)


def _v5_save(self):
    self.data.setdefault('settings',{})['active_profile']=getattr(self,'active_profile_name','Default')
    _v5_old_save(self)


def _v5_close(self,event):
    try:
        self.data.setdefault('settings',{})['v5_closed_at']=datetime.now().isoformat()
    except Exception: pass
    _v5_old_close(self,event)


def _v5_audio_state_changed(self,tab,audible):
    tab._v5_audio=bool(audible)
    try: tab._v5_audio_muted=bool(tab.view.page().isAudioMuted())
    except Exception: tab._v5_audio_muted=False
    try: self.tab_title_changed(tab,tab.view.title().strip())
    except Exception: pass


def _v5_page_load_metric(self,tab,ok):
    start=getattr(tab,'_v5_load_start',None)
    if start:
        ms=(time.monotonic()-start)*1000
        tab._v5_last_load_ms=ms
        if self.current_tab() is tab:
            self.statusBar().showMessage(f'Sayfa yükleme: {ms:.0f} ms',1800)


def _v5_perf_update(self):
    if psutil:
        vm=psutil.virtual_memory(); cpu=psutil.cpu_percent(interval=None)
        if not hasattr(self,'_v5_net_last'):
            n=psutil.net_io_counters(); self._v5_net_last=(n.bytes_sent,n.bytes_recv,time.monotonic())
            net_text='Ağ —'
        else:
            n=psutil.net_io_counters(); last_s,last_r,last_t=self._v5_net_last; dt=max(0.1,time.monotonic()-last_t); up=max(0,n.bytes_sent-last_s)/dt; down=max(0,n.bytes_recv-last_r)/dt; self._v5_net_last=(n.bytes_sent,n.bytes_recv,time.monotonic())
            net_text=f'↑{up/1024:.0f} KB/s ↓{down/1024:.0f} KB/s'
        self.performance_badge.setText(f'CPU {cpu:.0f}%  RAM {vm.percent:.0f}%  {net_text}')
    _v5_sleep_inactive(self)
    _v5_update_security_badge(self)


def _v5_create_perf_timer(self):
    if hasattr(self,'_v5_perf_timer'): return
    self._v5_perf_timer=QTimer(self); self._v5_perf_timer.timeout.connect(lambda: _v5_perf_update(self)); self._v5_perf_timer.start(2500)


def _v5_open_security(self): V5SecurityDialog(self).exec()
MainWindow.open_security_center=_v5_open_security
MainWindow.toggle_current_site_block=lambda self: _v5_toggle_site_block(self)
MainWindow.clear_current_site_cookies=lambda self: _v5_clear_current_site_cookies(self)
MainWindow.sleep_inactive_tabs=lambda self: _v5_sleep_inactive(self)
MainWindow.wake_all_tabs=lambda self: _v5_wake_all(self)
MainWindow.toggle_ai_panel=lambda self: _v5_toggle_ai(self)
MainWindow.open_advanced_center=lambda self: _v5_show_advanced(self)
MainWindow.tab_audio_state_changed=_v5_audio_state_changed
MainWindow.page_load_metric=_v5_page_load_metric

# Replace/extend tab groups with V5 version.
MainWindow.open_tab_groups=lambda self: V5TabGroupsDialog(self).exec()

BrowserTab.show_context_menu=_v5_patch_context_menu
_v5_patch_browser_tab_init()
MainWindow.setup_ui=_v5_setup_ui
MainWindow.current_tab_changed=_v5_current_changed
MainWindow.tab_url_changed=_v5_tab_url
MainWindow.download_requested=_v5_download
MainWindow.tab_title_changed=_v5_tab_title
MainWindow.save=_v5_save
MainWindow.closeEvent=_v5_close

# Security interceptor wrapper: blocked websites are denied before page load.
_old_intercept=OssAdBlocker.interceptRequest
def _v5_intercept(self, info):
    try:
        host = _v5_domain(info.requestUrl().toString())
        for blocked in getattr(self, "blocked_sites", set()):
            b = _v5_domain(blocked)
            if b and (host == b or host.endswith("." + b)):
                info.block(True)
                self.blocked_count += 1
                return
    except Exception:
        pass
    _old_intercept(self, info)
OssAdBlocker.blocked_sites=set()
OssAdBlocker.interceptRequest=_v5_intercept

# Keep interceptor's blocked-site list synchronized with stored settings.
def _v5_sync_blocked(browser):
    browser.ad_blocker.blocked_sites=set(browser.data.get('blocked_sites',[]))

_old_init_v5=MainWindow.__init__
def _v5_main_init(self):
    _old_init_v5(self)
    self.ad_blocker.blocked_sites=set(self.data.get('blocked_sites',[]))
    _v5_create_perf_timer(self)
MainWindow.__init__=_v5_main_init

# BrowserPage: site blocker + popup blocker.
_old_nav=BrowserPage.acceptNavigationRequest
def _v5_nav(self, url, nav_type, is_main_frame):
    if is_main_frame:
        host = _v5_domain(url.toString())
        blocked = {_v5_domain(item) for item in self.browser.data.get("blocked_sites", []) if _v5_domain(item)}
        if any(host == b or host.endswith("." + b) for b in blocked):
            self.browser.statusBar().showMessage(host + " engelli. Güvenlik Merkezi'nden engeli kaldırabilirsin.", 3500)
            return False
    return _old_nav(self, url, nav_type, is_main_frame)
BrowserPage.acceptNavigationRequest=_v5_nav

_old_create=BrowserPage.createWindow
def _v5_create_window(self,window_type):
    if bool(self.browser.data.get('settings',{}).get('block_popups',True)):
        try: self.browser.statusBar().showMessage('Açılır pencere engellendi.',1600)
        except Exception: pass
        return None
    return _old_create(self,window_type)
BrowserPage.createWindow=_v5_create_window

# Existing V4 wrapper already adds a V4 menu. Add V5 command center entries safely.
_old_cc_init=CommandCenterDialog.__init__
def _v5_cc_init(self,browser):
    _old_cc_init(self,browser)
    extras=[
        ('Gelişmiş Merkez',browser.open_advanced_center),
        ('Güvenlik Merkezi',browser.open_security_center),
        ('Performans Merkezi',lambda: V5PerformanceDialog(browser).exec()),
        ('YouTube Araçları',lambda: V5YouTubeDialog(browser).exec()),
        ('OSS AI Paneli',browser.toggle_ai_panel),
        ('Yedekleme / Senkronizasyon',lambda: V5BackupDialog(browser).exec()),
        ('Site Engelle',browser.toggle_current_site_block),
        ('Sekmeleri Uyandır',browser.wake_all_tabs),
    ]
    self.commands.extend(extras); self.refresh()
CommandCenterDialog.__init__=_v5_cc_init

# Load stored blocked sites once on the first profile object.
try:
    AD_BLOCKER.blocked_sites=set()
except Exception: pass

# Hardware acceleration setting must be chosen before QApplication is created.
_orig_main = main
def main():
    try:
        settings={}
        if DATA_FILE.exists():
            try: settings=json.loads(DATA_FILE.read_text(encoding='utf-8')).get('settings',{})
            except Exception: settings={}
        if settings.get('hardware_acceleration',True) is False:
            current=os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS','').strip()
            flags='--disable-gpu --disable-gpu-compositing'
            os.environ['QTWEBENGINE_CHROMIUM_FLAGS']=(current+' '+flags).strip()
    except Exception:
        pass
    _orig_main()



# ============================================================
# NOVA SEARCH — KENDİ DİZİNİ / KENDİ ARAMA MOTORU
# ============================================================
# NOVA Search dış arama motorlarından sonuç çekmez.
# Sonuçlar yalnızca NOVA'nın kendi SQLite web indeksinden gelir.
# Arka planda doğrudan siteler taranır; Google/Bing/DuckDuckGo API veya
# HTML sonuç sayfaları kullanılmaz.

import threading
import sqlite3
import queue
import gzip
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urldefrag, parse_qs

NOVA_SEARCH_NAME = "NOVA Search"
NOVA_SEARCH_HOST = "ossbrowser.local"
NOVA_SEARCH_PATH = "/search"
NOVA_REINDEX_PATH = "/reindex"
NOVA_HOME_URL = f"https://{NOVA_SEARCH_HOST}/home"
NOVA_DB = APP_DIR / "NOVAIndex" / "nova_web_index_v2.db"
NOVA_INDEX_DIR = APP_DIR / "NOVAIndex"
NOVA_MAX_PAGES = 12000
NOVA_MAX_DEPTH = 3
NOVA_WORKERS = 6
NOVA_PAGE_SIZE = 50
NOVA_MAX_HTML = 1500000
NOVA_USER_AGENT = "NOVA Search/1.0 (+OSS Browser local index)"

NOVA_SEEDS = [
    "https://www.python.org/",
    "https://docs.python.org/3/",
    "https://www.youtube.com/",
    "https://tr.wikipedia.org/wiki/Anasayfa",
    "https://tr.wikipedia.org/wiki/Minecraft",
    "https://www.technopat.net/",
    "https://www.donanimhaber.com/",
    "https://shiftdelete.net/",
    "https://www.webtekno.com/",
    "https://www.tamindir.com/",
    "https://pypi.org/",
    "https://github.com/",
    "https://docs.github.com/",
    "https://developer.mozilla.org/",
    "https://www.mozilla.org/",
    "https://stackoverflow.com/",
    "https://www.wikipedia.org/",
    "https://en.wikipedia.org/wiki/Main_Page",
    "https://www.w3.org/",
    "https://developer.android.com/",
    "https://learn.microsoft.com/",
    "https://nodejs.org/",
    "https://www.npmjs.com/",
    "https://www.linux.org/",
    "https://ubuntu.com/",
    "https://www.kernel.org/",
    "https://www.minecraft.net/",
    "https://minecraft.wiki/",
    "https://www.curseforge.com/minecraft",
    "https://modrinth.com/",
    "https://papermc.io/",
    "https://www.spigotmc.org/",
    "https://www.raspberrypi.com/",
    "https://www.arduino.cc/",
    "https://www.tensorflow.org/",
    "https://pytorch.org/",
    "https://www.djangoproject.com/",
    "https://flask.palletsprojects.com/",
]

# Kullanıcının seçebileceği arama motorları. NOVA kendi yerel indeksinden
# arar; Google, Bing ve DuckDuckGo ise kullanıcı özellikle seçtiğinde çalışır.
SEARCH_ENGINES = {
    "Google": "https://www.google.com/search?q={}",
    "Bing": "https://www.bing.com/search?q={}",
    "DuckDuckGo": "https://duckduckgo.com/?q={}",
    NOVA_SEARCH_NAME: None,
}

# HTML form action adresleri, arama şablonlarından ayrıdır. Form action
# içine '?q={}' koyulursa tarayıcı yanlış/boş sorgu üretebilir.
SEARCH_FORM_ACTIONS = {
    "Google": "https://www.google.com/search",
    "Bing": "https://www.bing.com/search",
    "DuckDuckGo": "https://duckduckgo.com/",
    NOVA_SEARCH_NAME: f"https://{NOVA_SEARCH_HOST}{NOVA_SEARCH_PATH}",
}


class _NovaHTMLParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = []
        self.text = []
        self.meta_description = ""
        self.links = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_map = {str(k).lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag in ("script", "style", "noscript", "svg"):
            self._skip_depth += 1
        elif tag == "meta":
            name = attrs_map.get("name", "").lower()
            if name in ("description", "og:description") and not self.meta_description:
                self.meta_description = str(attrs_map.get("content", "")).strip()
        elif tag == "a" and self._skip_depth == 0:
            href = str(attrs_map.get("href", "")).strip()
            if href:
                try:
                    absolute = urljoin(self.base_url, href)
                    absolute, _ = urldefrag(absolute)
                    parsed = urlparse(absolute)
                    if parsed.scheme in ("http", "https") and parsed.netloc:
                        self.links.append(absolute)
                except Exception:
                    pass

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style", "noscript", "svg") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth:
            return
        clean = " ".join(str(data).split())
        if not clean:
            return
        if self._in_title:
            self.title.append(clean)
        else:
            self.text.append(clean)


def _nova_default_bootstrap():
    return [
        ("YouTube", "https://www.youtube.com/", "YouTube resmi video platformu", "YouTube üzerinde videolar, müzik, oyun yayınları ve kanallar bulunur."),
        ("Türkçe Vikipedi", "https://tr.wikipedia.org/wiki/Anasayfa", "Türkçe özgür ansiklopedi", "Bilim, teknoloji, tarih, oyunlar ve genel bilgi konularında Türkçe ansiklopedi."),
        ("Minecraft — Türkçe Vikipedi", "https://tr.wikipedia.org/wiki/Minecraft", "Minecraft oyunu hakkında Türkçe bilgi", "Minecraft hayatta kalma, yaratıcı mod, bloklar, yaratıklar ve oyun mekanikleri hakkında Türkçe genel bilgi."),
        ("Technopat", "https://www.technopat.net/", "Türkçe teknoloji ve bilgisayar içerikleri", "Bilgisayar, donanım, yazılım, Windows ve oyunlar üzerine Türkçe içerikler ve rehberler."),
        ("DonanımHaber", "https://www.donanimhaber.com/", "Türkçe teknoloji haberleri", "Teknoloji, bilgisayar, telefon, oyun ve donanım üzerine Türkçe haberler."),
        ("ShiftDelete", "https://shiftdelete.net/", "Türkçe teknoloji haberleri", "Telefon, uygulama, yapay zekâ, bilgisayar ve dijital dünya üzerine Türkçe haberler."),
        ("Webtekno", "https://www.webtekno.com/", "Türkçe teknoloji ve bilim", "Teknoloji, bilim, internet, oyunlar ve dijital kültür hakkında Türkçe içerikler."),
        ("Tamindir", "https://www.tamindir.com/", "Türkçe yazılım ve indirme rehberleri", "Windows yazılımları, mobil uygulamalar, oyunlar ve teknoloji için Türkçe içerikler."),
        ("Python", "https://www.python.org/", "Python programming language", "Python programlama dili ve resmi proje sitesi."),
        ("Python Documentation", "https://docs.python.org/3/", "Python 3 documentation", "Python 3 resmi dokümantasyonu, standart kütüphane ve dil referansı."),
        ("PyPI", "https://pypi.org/", "Python Package Index", "Python paketleri ve açık kaynak Python projeleri için paket dizini."),
        ("GitHub", "https://github.com/", "GitHub", "Yazılım geliştirme, açık kaynak projeler ve kod depoları."),
        ("MDN Web Docs", "https://developer.mozilla.org/", "MDN Web Docs", "HTML, CSS, JavaScript ve web platformu dokümantasyonu."),
        ("Wikipedia", "https://www.wikipedia.org/", "Wikipedia", "Özgür ansiklopedi ve genel bilgi kaynağı."),
        ("Stack Overflow", "https://stackoverflow.com/", "Stack Overflow", "Programlama soruları ve cevapları topluluğu."),
        ("Microsoft Learn", "https://learn.microsoft.com/", "Microsoft Learn", "Windows, Azure, .NET ve Microsoft teknolojileri için dokümantasyon."),
        ("Android Developers", "https://developer.android.com/", "Android Developers", "Android geliştirme belgeleri, API'ler ve araçlar."),
        ("Node.js", "https://nodejs.org/", "Node.js", "JavaScript çalışma ortamı ve geliştirici kaynakları."),
        ("Linux", "https://www.linux.org/", "Linux", "Linux işletim sistemi ve topluluk kaynakları."),
        ("Ubuntu", "https://ubuntu.com/", "Ubuntu", "Ubuntu işletim sistemi ve açık kaynak ekosistemi."),
        ("Minecraft", "https://www.minecraft.net/", "Minecraft", "Minecraft resmi web sitesi ve oyun bilgileri."),
        ("Minecraft Wiki", "https://minecraft.wiki/", "Minecraft Wiki", "Minecraft mekanikleri, eşyalar, komutlar ve oyun bilgileri."),
        ("CurseForge Minecraft", "https://www.curseforge.com/minecraft", "CurseForge Minecraft", "Minecraft modları, modpackler, kaynak paketleri ve projeler."),
        ("Modrinth", "https://modrinth.com/", "Modrinth", "Minecraft modları, modpackler, shader ve kaynak paketleri."),
        ("PaperMC", "https://papermc.io/", "PaperMC", "Minecraft sunucu yazılımları ve Paper ekosistemi."),
        ("SpigotMC", "https://www.spigotmc.org/", "SpigotMC", "Minecraft sunucu eklentileri ve geliştirme topluluğu."),
        ("Raspberry Pi", "https://www.raspberrypi.com/", "Raspberry Pi", "Raspberry Pi bilgisayarları ve projeleri için resmi kaynak."),
        ("Arduino", "https://www.arduino.cc/", "Arduino", "Arduino kartları, elektronik projeler ve geliştirme ortamı."),
        ("TensorFlow", "https://www.tensorflow.org/", "TensorFlow", "Makine öğrenmesi ve yapay zeka için açık kaynak kütüphane."),
        ("PyTorch", "https://pytorch.org/", "PyTorch", "Makine öğrenmesi ve derin öğrenme geliştirme platformu."),
        ("Django", "https://www.djangoproject.com/", "Django", "Python ile web geliştirme framework'ü."),
        ("Flask", "https://flask.palletsprojects.com/", "Flask", "Python için hafif web framework dokümantasyonu."),
        ("W3C", "https://www.w3.org/", "World Wide Web Consortium", "Web standartları ve açık web teknolojileri."),
    ]


def _nova_category(url):
    host = (urlparse(url).hostname or "").lower()
    path = (urlparse(url).path or "").lower()
    if any(x in host for x in ("github", "stackoverflow", "pypi.org", "npmjs.com")):
        return "code"
    if "wiki" in host or "wikipedia" in host:
        return "wiki"
    if any(x in host for x in ("docs.", "developer.", "learn.", "python.org", "w3.org")):
        return "docs"
    if any(x in host for x in ("minecraft", "curseforge", "modrinth", "papermc", "spigotmc")):
        return "gaming"
    if any(x in path for x in ("/news", "/blog", "/article")):
        return "news"
    return "web"


def _nova_db_connect():
    NOVA_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(NOVA_DB), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("CREATE TABLE IF NOT EXISTS pages (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE NOT NULL, title TEXT NOT NULL DEFAULT '', snippet TEXT NOT NULL DEFAULT '', content TEXT NOT NULL DEFAULT '', domain TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'web', crawled_at INTEGER NOT NULL DEFAULT 0, depth INTEGER NOT NULL DEFAULT 0)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pages_domain ON pages(domain)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pages_title ON pages(title)")
    conn.commit()
    return conn


def _nova_bootstrap_db():
    conn = _nova_db_connect()
    for title, url, snippet, content in _nova_default_bootstrap():
        domain = (urlparse(url).hostname or "").lower().removeprefix("www.")
        conn.execute("INSERT INTO pages(url,title,snippet,content,domain,category,crawled_at,depth) VALUES(?,?,?,?,?,?,?,0) ON CONFLICT(url) DO UPDATE SET title=excluded.title,snippet=excluded.snippet", (url, title, snippet, content, domain, _nova_category(url), int(time.time())))
    conn.commit()
    conn.close()


def _nova_normalize_url(url):
    try:
        url, _ = urldefrag(str(url))
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.netloc:
            return ""
        return p._replace(fragment="").geturl()
    except Exception:
        return ""


def _nova_domain(url):
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _nova_clean(value):
    return html.unescape(re.sub(r"\s+", " ", str(value or "")).strip())


def _nova_fetch_page(url):
    request = urllib.request.Request(url, headers={"User-Agent": NOVA_USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.7", "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(request, timeout=8) as response:
        ctype = (response.headers.get("Content-Type") or "").lower()
        if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
            return None
        data = response.read(NOVA_MAX_HTML)
        if (response.headers.get("Content-Encoding") or "").lower() == "gzip":
            try:
                data = gzip.decompress(data)
            except Exception:
                pass
        encoding = response.headers.get_content_charset() or "utf-8"
        return data.decode(encoding, "ignore")


def _nova_extract_page(url, raw_html):
    parser = _NovaHTMLParser(url)
    parser.feed(raw_html)
    parser.close()
    title = _nova_clean(" ".join(parser.title)) or _nova_domain(url)
    text = _nova_clean(" ".join(parser.text))
    snippet = _nova_clean(parser.meta_description) or text[:320]
    links = []
    seen = set()
    for link in parser.links:
        link = _nova_normalize_url(link)
        if not link or link in seen:
            continue
        seen.add(link)
        links.append(link)
        if len(links) >= 80:
            break
    return {"url": url, "title": title[:240], "snippet": snippet[:700], "content": text[:12000], "domain": _nova_domain(url), "category": _nova_category(url), "links": links}


class _NovaCrawler:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.stop_flag = False
        self.pages = 0
        self.errors = 0
        self.queued = 0
        self.thread = None

    def start(self, force=False):
        with self.lock:
            if self.running:
                return False
            self.stop_flag = False
            self.running = True
            self.pages = 0
            self.errors = 0
            self.queued = len(NOVA_SEEDS)
        self.thread = threading.Thread(target=self._run, daemon=True, name="NOVA-Indexer")
        self.thread.start()
        return True

    def snapshot(self):
        try:
            conn = _nova_db_connect()
            total = int(conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0])
            conn.close()
        except Exception:
            total = 0
        with self.lock:
            return {"running": self.running, "pages": self.pages, "errors": self.errors, "queued": self.queued, "indexed": total}

    def _save_row(self, row):
        conn = _nova_db_connect()
        conn.execute("INSERT INTO pages(url,title,snippet,content,domain,category,crawled_at,depth) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET title=excluded.title,snippet=excluded.snippet,content=excluded.content,domain=excluded.domain,category=excluded.category,crawled_at=excluded.crawled_at,depth=excluded.depth", (row["url"], row["title"], row["snippet"], row["content"], row["domain"], row["category"], int(time.time()), row["depth"]))
        conn.commit()
        conn.close()

    def _run(self):
        seen = set(NOVA_SEEDS)
        seed_domains = {_nova_domain(u) for u in NOVA_SEEDS}
        pending = queue.Queue()
        for seed in NOVA_SEEDS:
            pending.put((seed, 0))
        try:
            with ThreadPoolExecutor(max_workers=NOVA_WORKERS, thread_name_prefix="NOVA-Fetch") as pool:
                futures = {}
                while (not pending.empty() or futures) and self.pages < NOVA_MAX_PAGES:
                    if self.stop_flag:
                        break
                    while len(futures) < NOVA_WORKERS and not pending.empty() and self.pages + len(futures) < NOVA_MAX_PAGES:
                        item = pending.get()
                        futures[pool.submit(self._fetch_one, item[0], item[1], seed_domains)] = item
                    if not futures:
                        break
                    done = next(as_completed(futures))
                    url, depth = futures.pop(done)
                    try:
                        row = done.result()
                        if row:
                            self._save_row(row)
                            self.pages += 1
                            if depth < NOVA_MAX_DEPTH:
                                for link in row["links"]:
                                    if link in seen:
                                        continue
                                    domain = _nova_domain(link)
                                    if not any(domain == d or domain.endswith("." + d) for d in seed_domains):
                                        continue
                                    seen.add(link)
                                    pending.put((link, depth + 1))
                    except Exception:
                        self.errors += 1
                        self.pages += 1
                    with self.lock:
                        self.queued = pending.qsize() + len(futures)
        finally:
            with self.lock:
                self.running = False
                self.queued = 0

    def _fetch_one(self, url, depth, seed_domains):
        try:
            raw = _nova_fetch_page(url)
            if not raw:
                return None
            host = _nova_domain(url)
            if not any(host == d or host.endswith("." + d) for d in seed_domains):
                return None
            row = _nova_extract_page(url, raw)
            row["depth"] = depth
            return row
        except Exception:
            return None


NOVA_TURKISH_DOMAINS = {
    "tr.wikipedia.org", "technopat.net", "donanimhaber.com", "shiftdelete.net",
    "webtekno.com", "tamindir.com", "sozcu.com.tr", "hurriyet.com.tr",
    "ntv.com.tr", "trthaber.com", "aa.com.tr", "haberler.com", "eksisozluk.com",
    "turkiye.gov.tr", "sahibinden.com", "hepsiburada.com", "trendyol.com",
    "oyungezer.com.tr", "technopat.net", "forum.donanimhaber.com",
}
NOVA_KNOWN_FOREIGN_DOMAINS = {
    "youtube.com", "google.com", "github.com", "python.org", "pypi.org",
    "stackoverflow.com", "mozilla.org", "developer.mozilla.org", "wikipedia.org",
    "microsoft.com", "android.com", "nodejs.org", "npmjs.com", "linux.org",
    "ubuntu.com", "kernel.org", "minecraft.net", "minecraft.wiki", "curseforge.com",
    "modrinth.com", "papermc.io", "spigotmc.org", "raspberrypi.com", "arduino.cc",
    "tensorflow.org", "pytorch.org", "djangoproject.com", "w3.org",
}
NOVA_TURKISH_HINTS = (
    " ve ", " için ", " nasıl ", " nedir ", " hakkında ", " türkçe ", " rehber ",
    " indir ", " kurulumu ", " kurulumu ", " ayarları ", " özellikleri ", " bilgisayar ",
    " oyunları ", " teknoloji ", " haberleri ", " güncellemesi ", " sorunları ", " çözümü ",
    " kullanımı ", " incelemesi ", " programı ", " uygulaması ", " ücretsiz ", " güvenli ",
)

def _nova_is_turkish_source(item):
    domain = _nova_domain(item.get("url", "")) or str(item.get("domain", "")).lower().removeprefix("www.")
    if not domain:
        return False
    # Explicit Turkish domains and known Turkish publishers are dependable signals.
    if domain.endswith(".tr") or domain in NOVA_TURKISH_DOMAINS:
        return True
    if any(domain.endswith("." + d) for d in NOVA_TURKISH_DOMAINS):
        return True
    # Known international sources are not marked Turkish merely because bootstrap text is localized.
    if domain in NOVA_KNOWN_FOREIGN_DOMAINS or any(domain.endswith("." + d) for d in NOVA_KNOWN_FOREIGN_DOMAINS):
        return False
    title = str(item.get("title", ""))
    snippet = str(item.get("snippet", ""))
    content = str(item.get("content", ""))
    combined = " " + _nova_clean(title + " " + snippet + " " + content[:1600]).lower() + " "
    turkish_chars = sum(1 for c in combined if c in "çğıöşü")
    hint_hits = sum(1 for hint in NOVA_TURKISH_HINTS if hint in combined)
    return turkish_chars >= 2 or hint_hits >= 2


def _nova_search_db(query, page=1, limit=NOVA_PAGE_SIZE, language_filter="turkish_only", category_filter="all", recency_filter="any"):
    query = _nova_clean(query)
    page = max(1, int(page or 1))
    if not query:
        return [], 0
    site_filter = ""
    title_filter = ""
    terms = []
    for token in re.findall(r'"[^\"]+"|\S+', query):
        lower = token.lower()
        if lower.startswith("site:"):
            site_filter = lower[5:].strip()
        elif lower.startswith("intitle:"):
            title_filter = lower[8:].strip().strip('"')
        else:
            clean_term = token.strip('"').lower()
            if clean_term:
                terms.append(clean_term)
    conn = _nova_db_connect()
    clauses = []
    args = []
    for term in terms[:8]:
        like = "%" + term + "%"
        clauses.append("(title LIKE ? OR url LIKE ? OR snippet LIKE ? OR content LIKE ?)")
        args.extend([like, like, like, like])
    if site_filter:
        clauses.append("(domain = ? OR domain LIKE ?)")
        args.extend([site_filter, "%" + "." + site_filter])
    if title_filter:
        clauses.append("title LIKE ?")
        args.append("%" + title_filter + "%")
    allowed_categories = {"docs", "code", "gaming", "wiki", "news", "web"}
    if category_filter in allowed_categories:
        clauses.append("category = ?")
        args.append(category_filter)
    if recency_filter == "week":
        clauses.append("crawled_at >= ?")
        args.append(int(time.time()) - 7 * 86400)
    elif recency_filter == "month":
        clauses.append("crawled_at >= ?")
        args.append(int(time.time()) - 30 * 86400)
    where = " AND ".join(clauses) if clauses else "1=1"
    rows = conn.execute(
        "SELECT url,title,snippet,content,domain,category FROM pages WHERE " + where + " LIMIT 6000", args
    ).fetchall()
    conn.close()

    phrase = " ".join(terms).strip()
    scored = []
    mode = language_filter if language_filter in ("all", "turkish_first", "turkish_only") else "turkish_only"
    for url, title, snippet, content, domain, category in rows:
        title = title or domain
        snippet = snippet or (content or "")[:320]
        title_l = str(title).lower()
        url_l = str(url).lower()
        snippet_l = str(snippet).lower()
        content_l = str(content or "").lower()
        item = {"url": url, "title": title, "snippet": snippet, "content": content or "", "domain": domain, "category": category}
        is_turkish = _nova_is_turkish_source(item)
        if mode == "turkish_only" and not is_turkish:
            continue
        score = 0
        for term in terms:
            if term in title_l: score += 20
            if title_l.startswith(term): score += 8
            if term in url_l: score += 7
            if term in snippet_l: score += 5
            if term in content_l: score += 1
        if phrase and phrase in (title_l + " " + snippet_l): score += 18
        if site_filter and (domain == site_filter or str(domain).endswith("." + site_filter)): score += 12
        if title_filter and title_filter in title_l: score += 20
        item["score"] = score
        item["is_turkish"] = is_turkish
        scored.append(item)
    if mode == "turkish_first":
        scored.sort(key=lambda item: (bool(item["is_turkish"]), item["score"], len(item["title"])), reverse=True)
    else:
        scored.sort(key=lambda item: (item["score"], len(item["title"])), reverse=True)
    total = len(scored)
    start = (page - 1) * limit
    results = [{key: value for key, value in item.items() if key not in ("content", "score", "is_turkish")} for item in scored[start:start + limit]]
    return results, total


def _nova_status_snapshot(browser):
    crawler = getattr(browser, "_nova_crawler", None)
    if crawler:
        return crawler.snapshot()
    return {"running": False, "indexed": 0, "pages": 0, "errors": 0, "queued": 0}


def _nova_home_html(engine_name="NOVA Search", shortcuts=None, browser=None):
    """NOVA'nın hızlı açılan, duyarlı ve etkileşimli başlangıç sayfası."""
    if engine_name not in SEARCH_ENGINES:
        engine_name = NOVA_SEARCH_NAME
    shortcuts = shortcuts if isinstance(shortcuts, list) else DEFAULT_HOME_SHORTCUTS
    cards = []
    for item in shortcuts:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "Site")).strip() or "Site"
        url = str(item.get("url", "")).strip()
        icon = str(item.get("icon", "●")).strip() or "●"
        if is_web_url(url):
            domain = _nova_domain(url)
            cards.append(
                f'<a class="site-card" href="{html.escape(url, quote=True)}" title="{html.escape(title, quote=True)}">'
                f'<span class="site-icon">{html.escape(icon)}</span>'
                f'<span class="site-copy"><strong>{html.escape(title)}</strong><small>{html.escape(domain)}</small></span>'
                f'<span class="site-arrow" aria-hidden="true">↗</span></a>'
            )
    if not cards:
        cards.append('<div class="empty-sites">Henüz hızlı bağlantı yok. Ana sayfa ayarlarından bağlantı ekleyebilirsin.</div>')

    action = SEARCH_FORM_ACTIONS.get(engine_name, SEARCH_FORM_ACTIONS[NOVA_SEARCH_NAME])
    snap = _nova_status_snapshot(browser) if browser is not None else {}
    indexed = int(snap.get("indexed", 0) or snap.get("pages", 0) or 0)
    queued = int(snap.get("queued", 0) or 0)
    running = bool(snap.get("running", False))
    index_state = "Dizin güncelleniyor" if running else "Yerel arama dizini hazır"
    engine_help = "Kendi yerel dizininde arar" if engine_name == NOVA_SEARCH_NAME else f"Aramalar {engine_name} üzerinden yapılır"
    return f'''<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">
<title>NOVA Search · OSS Browser</title>
<style>
:root{{--bg:#080b12;--line:rgba(151,174,216,.15);--muted:#8996ad;--text:#f5f7fc;--green:#5de0ad}}
*{{box-sizing:border-box}}
html{{min-height:100%;background:var(--bg)}}
body{{margin:0;min-height:100vh;color:var(--text);font-family:"Segoe UI",Inter,Arial,sans-serif;background:radial-gradient(ellipse at 13% 0%,rgba(62,89,176,.27),transparent 35%),radial-gradient(ellipse at 92% 18%,rgba(105,63,191,.15),transparent 28%),linear-gradient(155deg,#0b1020 0%,#080b12 50%,#090d15 100%);}}
a{{color:inherit}}
.page{{width:min(1120px,92vw);margin:0 auto;padding:22px 0 28px}}
.topbar{{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:30px}}
.brand-lockup{{display:flex;align-items:center;gap:11px;min-width:0}}
.logo{{width:42px;height:42px;display:grid;place-items:center;border-radius:14px;color:white;font-size:22px;font-weight:950;background:linear-gradient(140deg,#8a68ff,#48bcff);box-shadow:0 8px 28px rgba(117,99,255,.25)}}
.brand-name{{font-weight:850;letter-spacing:.1px;font-size:15px}}
.brand-caption{{margin-top:3px;color:#7f8da5;font-size:11px}}
.top-actions{{display:flex;align-items:center;gap:9px;flex-wrap:wrap;justify-content:flex-end}}
.pill{{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);border-radius:999px;background:rgba(19,29,46,.72);padding:8px 11px;color:#b8c4d9;font-size:11px;white-space:nowrap}}
.dot{{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 12px rgba(93,224,173,.45)}}
.hero{{text-align:center;padding:8px 0 20px}}
.hero-eyebrow{{display:inline-flex;align-items:center;gap:8px;color:#b9adff;background:rgba(128,103,255,.09);border:1px solid rgba(151,125,255,.22);border-radius:999px;padding:7px 12px;font-size:11px;font-weight:750;letter-spacing:.2px}}
.spark{{color:#80d9ff;font-size:14px}}
h1{{font-size:clamp(35px,5.3vw,59px);line-height:1.06;letter-spacing:-2.1px;margin:18px 0 12px;font-weight:880}}
.gradient{{background:linear-gradient(100deg,#a18dff 7%,#69bcff 55%,#72e6d4 98%);background-clip:text;-webkit-background-clip:text;color:transparent}}
.lead{{max-width:610px;margin:0 auto;color:#9ba8be;line-height:1.65;font-size:14px}}
.search-wrap{{max-width:810px;margin:26px auto 0}}
.search{{display:flex;align-items:center;gap:9px;padding:7px 8px 7px 16px;border:1px solid rgba(133,159,208,.28);border-radius:19px;background:rgba(15,22,35,.94);box-shadow:0 17px 55px rgba(0,0,0,.28),0 0 0 5px rgba(117,99,255,.035);transition:border-color .18s,box-shadow .18s}}
.search:focus-within{{border-color:rgba(144,119,255,.8);box-shadow:0 17px 55px rgba(0,0,0,.28),0 0 0 4px rgba(117,99,255,.12)}}
.search-icon{{color:#8291ab;font-size:23px;flex:0 0 auto}}
.search input{{flex:1;min-width:0;border:0;outline:0;background:transparent;color:#f5f7fc;font:inherit;font-size:16px;padding:12px 4px}}
.search input::placeholder{{color:#65748c}}
.search button{{border:0;border-radius:13px;background:linear-gradient(135deg,#8f70ff,#6e55ee);color:white;padding:13px 24px;font-weight:800;font-size:13px;cursor:pointer;box-shadow:0 7px 20px rgba(113,82,235,.2);transition:transform .18s,filter .18s}}
.search button:hover{{filter:brightness(1.12);transform:translateY(-1px)}}
.discover{{margin:24px auto 0;max-width:990px;padding:18px;border:1px solid rgba(139,161,204,.16);border-radius:22px;background:linear-gradient(135deg,rgba(18,27,44,.84),rgba(12,17,28,.82));box-shadow:0 18px 50px rgba(0,0,0,.16);position:relative;overflow:hidden}}
.discover:before{{content:"";position:absolute;width:260px;height:180px;right:-90px;top:-110px;background:rgba(127,96,255,.13);filter:blur(32px);pointer-events:none}}
.discover-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;margin-bottom:15px;position:relative}}
.discover-kicker{{display:inline-flex;align-items:center;gap:6px;color:#bcaeff;font-size:9px;font-weight:850;letter-spacing:1.4px;text-transform:uppercase}}
.discover-heading{{font-size:17px;font-weight:850;letter-spacing:-.35px;margin:5px 0 4px}}
.discover-desc{{margin:0;color:#8795ab;font-size:11px;line-height:1.55}}
.discover-badge{{display:flex;align-items:center;gap:7px;white-space:nowrap;border:1px solid rgba(130,157,204,.15);background:rgba(8,13,22,.42);border-radius:999px;padding:8px 10px;color:#aab7ce;font-size:10px}}
.discover-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;position:relative}}
.discover-card{{display:flex;align-items:center;gap:10px;min-width:0;padding:12px;border-radius:15px;border:1px solid rgba(135,157,199,.13);background:rgba(7,12,21,.42);text-decoration:none;transition:transform .16s,border-color .16s,background .16s}}
.discover-card:hover{{transform:translateY(-2px);border-color:rgba(145,126,255,.42);background:rgba(31,40,62,.65)}}
.discover-icon{{display:grid;place-items:center;width:37px;height:37px;flex:0 0 37px;border-radius:12px;font-size:17px;font-weight:800;background:linear-gradient(145deg,#252d48,#172236);color:#d7ddff;border:1px solid rgba(157,172,221,.12)}}
.discover-icon.cyan{{color:#83e8ef;background:linear-gradient(145deg,#193b49,#15283c)}}.discover-icon.green{{color:#8ee9be;background:linear-gradient(145deg,#1a3c37,#172a32)}}.discover-icon.orange{{color:#ffcf91;background:linear-gradient(145deg,#443326,#292238)}}
.discover-copy{{min-width:0;flex:1}}
.discover-copy strong{{display:block;color:#e8edf8;font-size:11px;font-weight:800;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.discover-copy small{{display:block;color:#7f8da5;font-size:9px;line-height:1.4;margin-top:4px}}
.discover-arrow{{color:#647594;font-size:13px;align-self:flex-start}}
.discover-foot{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;border-top:1px solid rgba(137,157,198,.1);margin-top:14px;padding-top:12px;position:relative}}
.discover-foot-label{{color:#64738b;font-size:9px;font-weight:800;letter-spacing:1px}}
.discover-links{{display:flex;gap:8px;flex-wrap:wrap}}
.discover-links a{{font-size:10px;color:#aab9d2;text-decoration:none;border:1px solid rgba(135,157,199,.12);border-radius:8px;padding:6px 9px;background:rgba(8,13,22,.32)}}
.discover-links a:hover{{color:#fff;border-color:rgba(145,126,255,.35)}}
@media(max-width:800px){{.discover-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.discover-head{{align-items:flex-start}}}}
@media(max-width:480px){{.discover{{padding:13px}}.discover-grid{{grid-template-columns:1fr}}.discover-badge{{display:none}}}}
.content{{margin-top:32px}}
.section-head{{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin:0 0 14px}}
.section-title{{font-size:16px;font-weight:820;letter-spacing:-.2px}}
.section-caption{{color:#718099;font-size:11px;margin-top:5px}}
.text-link{{font-size:11px;text-decoration:none;color:#b6aaff;display:inline-flex;align-items:center;gap:6px;white-space:nowrap}}
.text-link:hover{{color:white}}
.sites{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}
.site-card{{position:relative;display:flex;align-items:center;gap:12px;min-width:0;padding:15px 14px;border-radius:17px;border:1px solid var(--line);background:linear-gradient(145deg,rgba(18,28,44,.92),rgba(12,18,29,.96));text-decoration:none;transition:transform .18s,border-color .18s,background .18s;overflow:hidden}}
.site-card:before{{content:"";position:absolute;inset:0;background:linear-gradient(110deg,rgba(123,101,255,.07),transparent 52%);opacity:0;transition:opacity .18s}}
.site-card:hover{{transform:translateY(-3px);border-color:rgba(145,126,255,.4);background:#131d2d}}
.site-card:hover:before{{opacity:1}}
.site-icon{{position:relative;display:grid;place-items:center;flex:0 0 39px;width:39px;height:39px;border:1px solid rgba(146,169,214,.12);border-radius:13px;background:linear-gradient(145deg,#1c2a43,#151e2f);font-size:17px;color:#d7e4ff}}
.site-copy{{position:relative;min-width:0;display:flex;flex-direction:column;gap:4px;flex:1}}
.site-copy strong{{font-size:12px;font-weight:780;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.site-copy small{{font-size:10px;color:#77869e;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.site-arrow{{position:relative;color:#576a89;opacity:0;transition:opacity .18s,transform .18s;font-size:14px}}
.site-card:hover .site-arrow{{opacity:1;transform:translate(1px,-1px)}}
.empty-sites{{grid-column:1/-1;border:1px dashed var(--line);border-radius:14px;padding:20px;color:var(--muted);font-size:12px}}
.lower-grid{{display:grid;grid-template-columns:1.2fr .8fr;gap:13px;margin-top:23px}}
.panel{{min-width:0;border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,rgba(16,24,38,.88),rgba(11,17,27,.85));padding:17px}}
.panel-head{{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:13px}}
.panel-title{{font-size:13px;font-weight:820}}
.panel-kicker{{font-size:10px;color:#75849d}}
.index-status{{display:flex;align-items:center;gap:10px;padding:11px;border-radius:13px;background:rgba(22,34,51,.78);border:1px solid rgba(140,162,201,.1)}}
.status-icon{{flex:0 0 35px;width:35px;height:35px;border-radius:11px;display:grid;place-items:center;background:rgba(94,221,177,.09);color:#77e6be;font-size:16px}}
.status-copy{{min-width:0;flex:1}}
.status-copy strong{{font-size:12px;display:block}}
.status-copy small{{display:block;color:#7e8ba2;font-size:10px;margin-top:4px}}
.status-live{{font-size:10px;color:#6de1b3;white-space:nowrap}}
.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}}
.stat{{padding:10px 11px;border-radius:12px;border:1px solid rgba(140,162,201,.1);background:rgba(12,18,29,.55)}}
.stat strong{{display:block;font-size:17px;letter-spacing:-.5px}}
.stat span{{display:block;color:#74839b;font-size:10px;margin-top:4px}}
.tools-list{{display:grid;gap:8px}}
.tool{{display:flex;align-items:center;gap:10px;padding:9px 10px;border:1px solid rgba(140,162,201,.1);background:rgba(12,18,29,.48);border-radius:12px;cursor:pointer;text-align:left;color:#dbe3f2;font:inherit;width:100%;transition:border-color .16s,background .16s}}
.tool:hover{{border-color:rgba(144,119,255,.35);background:rgba(112,87,225,.08)}}
.tool-icon{{display:grid;place-items:center;width:30px;height:30px;flex:0 0 30px;border-radius:9px;background:#1a263a;color:#b7c6e3;font-size:13px}}
.tool-copy{{flex:1;min-width:0}}
.tool-copy b{{display:block;font-size:11px;font-weight:750}}
.tool-copy small{{display:block;margin-top:3px;font-size:10px;color:#7a89a0}}
.tool-arrow{{color:#677792}}
.bottom-row{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-top:22px;padding-top:14px;border-top:1px solid rgba(140,162,201,.1);color:#62718a;font-size:10px}}
.bottom-links{{display:flex;gap:14px;flex-wrap:wrap}}
.bottom-links a{{color:#8694aa;text-decoration:none}}
.bottom-links a:hover{{color:#c4b9ff}}
@media(max-width:800px){{.sites{{grid-template-columns:repeat(2,minmax(0,1fr))}}.lower-grid{{grid-template-columns:1fr}}.topbar{{margin-bottom:24px}}.page{{padding-top:16px}}}}
@media(max-width:480px){{.sites{{grid-template-columns:1fr}}.search{{gap:5px;padding-left:11px}}.search input{{font-size:14px}}.search button{{padding:12px 14px}}h1{{letter-spacing:-1.4px}}.pill.engine-pill{{display:none}}.stats{{grid-template-columns:repeat(3,minmax(0,1fr))}}.stat{{padding:10px 8px}}.stat strong{{font-size:15px}}}}
</style>
</head>
<body>
<div class="page">
  <header class="topbar">
    <div class="brand-lockup"><div class="logo">N</div><div><div class="brand-name">NOVA <span style="color:#9d8cff">Search</span></div><div class="brand-caption">OSS Browser için akıllı başlangıç sayfası</div></div></div>
    <div class="top-actions"><span class="pill"><span class="dot"></span> Yerel dizin etkin</span><span class="pill engine-pill">Motor: <b>{html.escape(engine_name)}</b></span></div>
  </header>
  <main>
    <section class="hero">
      <div class="hero-eyebrow"><span class="spark">✦</span> ARAMAYA YENİ BİR BAKIŞ</div>
      <h1>Merak ettiğini <span class="gradient">keşfet.</span></h1>
      <p class="lead">Web'de aradığını bul, sevdiğin sitelere hızlıca git. NOVA'nın yerel arama dizinini veya seçtiğin arama motorunu kullan.</p>
      <div class="search-wrap">
        <form class="search" action="{action}" method="get" id="searchForm">
          <span class="search-icon" aria-hidden="true">⌕</span>
          <input id="q" name="q" autofocus autocomplete="off" spellcheck="false" placeholder="Bir şey ara… ör. Minecraft, Python, Windows 11" aria-label="Aranacak ifade">
          <button type="submit">Ara <span aria-hidden="true">→</span></button>
        </form>
        <section class="discover" aria-label="Keşfet sayfası">
          <div class="discover-head">
            <div><span class="discover-kicker">✦ OSS KEŞFET</span><h2 class="discover-heading">Merak ettiğin konulara göz at</h2><p class="discover-desc">Arama kısayolları yerine, seçilmiş kaynaklardan oluşan keşif alanı.</p></div>
            <div class="discover-badge"><span class="dot"></span> Kaynakları keşfet</div>
          </div>
          <div class="discover-grid">
            <a class="discover-card" href="https://github.com/explore"><span class="discover-icon">⌘</span><span class="discover-copy"><strong>Yazılım ve projeler</strong><small>Açık kaynak araçları ve yeni projeler</small></span><span class="discover-arrow">↗</span></a>
            <a class="discover-card" href="https://www.minecraft.net/"><span class="discover-icon orange">◆</span><span class="discover-copy"><strong>Oyun dünyası</strong><small>Minecraft ve oyun içerikleri</small></span><span class="discover-arrow">↗</span></a>
            <a class="discover-card" href="https://science.nasa.gov/"><span class="discover-icon cyan">✦</span><span class="discover-copy"><strong>Bilim ve uzay</strong><small>Uzay görevleri ve bilimsel keşifler</small></span><span class="discover-arrow">↗</span></a>
            <a class="discover-card" href="https://www.python.org/"><span class="discover-icon green">Py</span><span class="discover-copy"><strong>Öğren ve geliştir</strong><small>Python ve programlama kaynakları</small></span><span class="discover-arrow">↗</span></a>
          </div>
          <div class="discover-foot"><span class="discover-foot-label">BAŞLANGIÇ KAYNAKLARI</span><div class="discover-links"><a href="https://developer.mozilla.org/">MDN Web Docs ↗</a><a href="https://learn.microsoft.com/">Microsoft Learn ↗</a><a href="https://stackoverflow.com/">Stack Overflow ↗</a><a href="https://www.wikipedia.org/">Wikipedia ↗</a></div></div>
        </section>
      </div>
    </section>
    <section class="content">
      <div class="section-head"><div><div class="section-title">Hızlı erişim</div><div class="section-caption">Sık kullandığın siteler tek tık uzağında</div></div><a class="text-link" href="https://{NOVA_SEARCH_HOST}{NOVA_REINDEX_PATH}">↻ NOVA dizinini güncelle</a></div>
      <div class="sites">{''.join(cards)}</div>
    </section>
    <section class="lower-grid">
      <div class="panel">
        <div class="panel-head"><div class="panel-title">NOVA dizin durumu</div><span class="panel-kicker">GERÇEK ZAMANLI DURUM</span></div>
        <div class="index-status"><div class="status-icon">⌕</div><div class="status-copy"><strong>{html.escape(index_state)}</strong><small>{html.escape(engine_help)}</small></div><span class="status-live">● {"ÇALIŞIYOR" if running else "HAZIR"}</span></div>
        <div class="stats"><div class="stat"><strong>{indexed:,}</strong><span>İndekslenen sayfa</span></div><div class="stat"><strong>{queued:,}</strong><span>Kuyruktaki sayfa</span></div><div class="stat"><strong>{"Açık" if engine_name == NOVA_SEARCH_NAME else "Harici"}</strong><span>Arama kaynağı</span></div></div>
      </div>
      <div class="panel">
        <div class="panel-head"><div class="panel-title">Arama ipuçları</div><span class="panel-kicker">DAHA İYİ SONUÇLAR</span></div>
        <div class="tools-list">
          <button class="tool" type="button" onclick="setQuery('site:python.org Python kurulumu')"><span class="tool-icon">⌘</span><span class="tool-copy"><b>Belirli bir sitede ara</b><small>site:python.org Python kurulumu</small></span><span class="tool-arrow">↗</span></button>
          <button class="tool" type="button" onclick="setQuery('intitle:Minecraft modları')"><span class="tool-icon">▤</span><span class="tool-copy"><b>Başlıkta kelime ara</b><small>intitle:Minecraft modları</small></span><span class="tool-arrow">↗</span></button>
          <button class="tool" type="button" onclick="document.getElementById('q').focus()"><span class="tool-icon">⌕</span><span class="tool-copy"><b>Yeni arama başlat</b><small>Arama alanına dön</small></span><span class="tool-arrow">→</span></button>
        </div>
      </div>
    </section>
  </main>
  <footer class="bottom-row"><span>© OSS Browser · NOVA Search · Yerel indeks tabanlı arama</span><div class="bottom-links"><a href="https://{NOVA_SEARCH_HOST}{NOVA_REINDEX_PATH}">Dizini yenile</a><a href="https://www.wikipedia.org/">Wikipedia</a><a href="https://github.com/">GitHub</a></div></footer>
</div>
<script>
function setQuery(value){{var input=document.getElementById('q');input.value=value;input.focus();}}
document.addEventListener('keydown',function(event){{if(event.key==='/' && !event.ctrlKey && !event.altKey && document.activeElement.tagName!=='INPUT' && document.activeElement.tagName!=='TEXTAREA'){{event.preventDefault();document.getElementById('q').focus();}}}});
</script>
</body></html>'''

def _nova_result_html(browser, query, results, total, page):
    snap = _nova_status_snapshot(browser)
    q = html.escape(query, quote=True)
    mode = browser.data.get("settings", {}).get("nova_language_filter", "turkish_only")
    mode_label = {
        "turkish_only": "Yabancı siteler gizli",
        "turkish_first": "Türkçe kaynaklar öncelikli",
        "all": "Tüm diller açık",
    }.get(mode, "Yabancı siteler gizli")
    cards = []
    for item in results:
        cards.append(f'<article class="result"><div class="topline"><span class="badge">{html.escape(str(item.get("category", "web")).upper())}</span><span class="domain">{html.escape(item.get("domain", ""))}</span></div><a class="title" href="{html.escape(item.get("url", ""), quote=True)}">{html.escape(item.get("title", ""))}</a><div class="url">{html.escape(item.get("url", ""))}</div><p>{html.escape(item.get("snippet", ""))}</p></article>')
    body = ''.join(cards) if cards else '<div class="empty"><b>Bu aramada sonuç yok.</b><br><span>NOVA kendi dizinini büyütüyor. Dizin güncelleme bağlantısıyla daha fazla site taratabilirsin.</span></div>'
    prev_link = '' if page <= 1 else f'<a href="https://{NOVA_SEARCH_HOST}{NOVA_SEARCH_PATH}?q={quote_plus(query)}&p={page-1}">← Önceki</a>'
    next_link = '' if page * NOVA_PAGE_SIZE >= total else f'<a href="https://{NOVA_SEARCH_HOST}{NOVA_SEARCH_PATH}?q={quote_plus(query)}&p={page+1}">Sonraki →</a>'
    return f'''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NOVA Search — {q}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#080c14;color:#f3f6fb;font-family:"Segoe UI",Arial,sans-serif}}.wrap{{width:min(1080px,94vw);margin:auto;padding:22px 0 60px}}.nav{{display:flex;align-items:center;gap:12px;margin-bottom:16px}}.n{{width:42px;height:42px;display:grid;place-items:center;border-radius:12px;background:linear-gradient(135deg,#7c5cff,#43b9ff);font-weight:950}}.brand{{font-size:18px;font-weight:850}}.sub{{font-size:11px;color:#748198}}.search{{display:flex;gap:8px;padding:6px;background:#111a27;border:1px solid #27344a;border-radius:17px}}.search input{{flex:1;min-width:0;background:transparent;border:0;outline:0;color:#fff;padding:12px 13px;font-size:16px}}.search button{{border:0;border-radius:12px;background:#7c5cff;color:#fff;padding:0 19px;font-weight:800}}.meta{{display:flex;justify-content:space-between;gap:15px;margin:14px 2px;color:#7b899f;font-size:12px}}.result{{background:#0f1723;border:1px solid #202c40;border-radius:16px;padding:16px 17px;margin:11px 0}}.topline{{display:flex;gap:8px;align-items:center;margin-bottom:7px}}.badge{{padding:3px 7px;border-radius:999px;background:#18243a;color:#9eb2d2;font-size:9px;font-weight:800}}.domain{{color:#73d9a0;font-size:11px}}.title{{color:#aec0ff;text-decoration:none;font-size:19px;font-weight:750}}.title:hover{{text-decoration:underline}}.url{{color:#68778f;font-size:10px;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}p{{color:#b5c0d0;line-height:1.55;font-size:13px;margin:9px 0 0}}.pager{{display:flex;justify-content:space-between;margin-top:18px}}.pager a{{color:#bcc8dc;text-decoration:none;background:#111a27;border:1px solid #253249;padding:9px 13px;border-radius:10px}}.empty{{padding:55px 20px;text-align:center;color:#93a1b6;background:#0f1723;border:1px solid #202c40;border-radius:16px}}.empty span{{display:inline-block;margin-top:8px;color:#6f7e95;font-size:12px}}.note{{text-align:center;color:#56657b;font-size:10px;margin-top:20px}}</style></head><body><div class="wrap"><div class="nav"><div class="n">N</div><div><div class="brand">NOVA Search</div><div class="sub">Kendi web indeksi · NOVA sonuçları</div></div></div><form class="search" action="https://{NOVA_SEARCH_HOST}{NOVA_SEARCH_PATH}" method="get"><input name="q" value="{q}" autofocus autocomplete="off"><button type="submit">Ara</button></form><div class="meta"><span>"{q}" için {total:,} eşleşme</span><span>{len(results)} sonuç · {html.escape(mode_label)}</span></div>{body}<div class="pager">{prev_link}<span></span>{next_link}</div><div class="note">NOVA sonuçları yalnızca kendi yerel indeksinden üretir.</div></div></body></html>'''


def _nova_start_crawler(self, force=False):
    crawler = getattr(self, "_nova_crawler", None)
    if crawler is None:
        crawler = _NovaCrawler()
        self._nova_crawler = crawler
    started = crawler.start(force=force)
    if started:
        try:
            self.statusBar().showMessage("NOVA kendi web dizinini güncelliyor...", 2500)
        except Exception:
            pass
    return started


def _nova_resolve_direct_site(query):
    value = _nova_clean(query).lower().strip().strip('"\'')
    value = value.removeprefix("https://").removeprefix("http://").removeprefix("www.").rstrip("/")
    aliases = {
        "youtube": "https://www.youtube.com/", "youtube.com": "https://www.youtube.com/",
        "google": "https://www.google.com/", "google.com": "https://www.google.com/",
        "gmail": "https://mail.google.com/", "gmail.com": "https://mail.google.com/",
        "whatsapp": "https://web.whatsapp.com/", "whatsapp.com": "https://web.whatsapp.com/",
        "github": "https://github.com/", "github.com": "https://github.com/",
        "minecraft": "https://www.minecraft.net/", "minecraft.net": "https://www.minecraft.net/",
        "minecraft wiki": "https://minecraft.wiki/", "minecraft.wiki": "https://minecraft.wiki/",
        "modrinth": "https://modrinth.com/", "modrinth.com": "https://modrinth.com/",
        "curseforge": "https://www.curseforge.com/", "curseforge.com": "https://www.curseforge.com/",
        "roblox": "https://www.roblox.com/", "roblox.com": "https://www.roblox.com/",
        "reddit": "https://www.reddit.com/", "reddit.com": "https://www.reddit.com/",
        "twitch": "https://www.twitch.tv/", "twitch.tv": "https://www.twitch.tv/",
        "facebook": "https://www.facebook.com/", "facebook.com": "https://www.facebook.com/",
        "instagram": "https://www.instagram.com/", "instagram.com": "https://www.instagram.com/",
        "x": "https://x.com/", "x.com": "https://x.com/",
    }
    return aliases.get(value)


def _nova_looks_like_domain(text):
    value = str(text or "").strip()
    if not value or any(ch.isspace() for ch in value):
        return False
    # Do not treat bare words such as "youtube" as a domain; only clear hostnames are opened.
    return bool(re.match(r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[A-Za-z]{2,}(?::\d+)?(?:/[^ ]*)?$", value))


def _nova_search(self, query, page=1):
    query = _nova_clean(query)
    if not query:
        return
    direct_site = _nova_resolve_direct_site(query)
    if direct_site and page == 1:
        tab = self.current_tab()
        if not isinstance(tab, BrowserTab):
            tab = self.new_tab()
        tab.is_home = False
        tab.view.setUrl(QUrl(direct_site))
        self.url_bar.setText(direct_site)
        self.statusBar().showMessage("NOVA: eşleşen site açılıyor → " + urlparse(direct_site).hostname, 2500)
        return
    settings = self.data.get("settings", {})
    language_filter = settings.get("nova_language_filter", "turkish_only")
    category_filter = settings.get("nova_category_filter", "all")
    recency_filter = settings.get("nova_recency_filter", "any")
    default_site = str(settings.get("nova_default_site_filter", "")).strip().lower()
    if default_site and not re.search(r"\bsite:", query, flags=re.I):
        query = query + " site:" + default_site
    results, total = _nova_search_db(
        query, page=page, limit=NOVA_PAGE_SIZE,
        language_filter=language_filter,
        category_filter=category_filter,
        recency_filter=recency_filter,
    )
    tab = self.current_tab()
    if not isinstance(tab, BrowserTab):
        tab = self.new_tab()
    tab.is_home = False
    tab.view.setHtml(_nova_result_html(self, query, results, total, page), QUrl("about:blank"))
    self.url_bar.setText(query)
    self.statusBar().showMessage(f"NOVA: {total:,} eşleşme · {len(results)} sonuç gösteriliyor", 2300)


def _nova_status_update(browser):
    try:
        snap = _nova_status_snapshot(browser)
        if snap["running"]:
            browser.statusBar().showMessage(f"NOVA dizini: {snap['indexed']:,} sayfa · taranıyor · kuyruk {snap['queued']:,}", 1200)
    except Exception:
        pass


def _nova_set_home(self):
    self.is_home = True
    engine = self.browser.data.get("settings", {}).get("search_engine", NOVA_SEARCH_NAME)
    self.view.setHtml(_nova_home_html(engine, self.browser.data.get("home_shortcuts", DEFAULT_HOME_SHORTCUTS), self.browser), QUrl("about:blank"))


def _nova_nav(self, url, nav_type, is_main_frame):
    if is_main_frame:
        try:
            host = (url.host() or "").lower()
            path = (url.path() or "").rstrip("/")
            if host == NOVA_SEARCH_HOST:
                params = parse_qs(url.query(), keep_blank_values=True)
                query = _nova_clean(params.get("q", [""])[0])
                if path == NOVA_SEARCH_PATH:
                    page = int(params.get("p", ["1"])[0] or 1)
                    QTimer.singleShot(0, lambda q=query, p=page: self.browser._nova_search(q, p))
                    return False
                if path == NOVA_REINDEX_PATH:
                    QTimer.singleShot(0, lambda: _nova_start_crawler(self.browser, force=True))
                    return False
        except Exception:
            return False
    return _nova_base_navigation(self, url, nav_type, is_main_frame)


def _nova_navigate(self):
    text = self.url_bar.text().strip()
    if not text:
        return
    if text.startswith(("http://", "https://")):
        view = self.current_view()
        if view:
            view.setUrl(QUrl(text))
        return
    if _nova_looks_like_domain(text):
        view = self.current_view()
        if view:
            view.setUrl(QUrl("https://" + text))
        return
    engine = self.data.get("settings", {}).get("search_engine", "Google")
    if engine == NOVA_SEARCH_NAME:
        self._nova_search(text, 1)
    else:
        # MainWindow's original navigation uses the selected Google/Bing/DDG template.
        _nova_base_navigate(self)


def _nova_init(self, *args, **kwargs):
    _nova_base_init(self, *args, **kwargs)
    try:
        _nova_bootstrap_db()
        self._nova_crawler = _NovaCrawler()
        self._nova_status_timer = QTimer(self)
        self._nova_status_timer.setInterval(1000)
        self._nova_status_timer.timeout.connect(lambda: _nova_status_update(self))
        self._nova_status_timer.start()
        _nova_start_crawler(self, force=False)
        settings = self.data.setdefault("settings", {})
        saved_engine = settings.get("search_engine")
        # Bir kullanıcı eski sürümde Google/Bing/DDG seçmişse onu bozma.
        # Eksik/geçersiz ayarda NOVA kullanılır; üç eski motor da seçilebilir kalır.
        if saved_engine not in SEARCH_ENGINES:
            settings["search_engine"] = NOVA_SEARCH_NAME
            self.save()
        settings.setdefault("nova_default_initialized", True)
    except Exception as exc:
        try:
            self.statusBar().showMessage("NOVA: " + str(exc), 3000)
        except Exception:
            pass


# Capture the previous browser behavior exactly once, then install the clean NOVA layer.
_nova_base_navigation = BrowserPage.acceptNavigationRequest
_nova_base_navigate = MainWindow.navigate
_nova_base_init = MainWindow.__init__

BrowserPage.acceptNavigationRequest = _nova_nav
BrowserTab.set_home = _nova_set_home
MainWindow.navigate = _nova_navigate
MainWindow._nova_search = _nova_search
MainWindow.__init__ = _nova_init


# ============================================================
# OSS BROWSER — WEBSITE UPDATE SYSTEM
# ============================================================
# Configure the public website's /updates/latest.json from the OSS menu.
# The app downloads the new ZIP and replaces the running .py AFTER exit.

# Do not hard-code a RAR/Temp path here: it changes when the archive is extracted.
# The user can set a public HTTPS URL or a local file:///.../updates/latest.json.
UPDATE_MANIFEST_URL = ""
UPDATE_CHECK_TIMEOUT = 8


def _oss_update_find_local_manifest(self=None):
    """Find a nearby manifest for local testing without relying on Temp paths."""
    try:
        script_dir = Path(sys.argv[0]).resolve().parent
    except Exception:
        script_dir = Path.cwd()
    candidates = (
        script_dir / "updates" / "latest.json",
        script_dir / "oss_browser_update_site" / "updates" / "latest.json",
        script_dir / "website" / "updates" / "latest.json",
    )
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve().as_uri()
        except Exception:
            pass
    return ""


def _oss_update_source(self):
    try:
        value = str(self.data.get("settings", {}).get("update_url", "")).strip()
    except Exception:
        value = ""

    # Old sample links and temporary paths commonly become stale. Ask for a
    # real address instead of repeatedly trying an invalid server/path.
    if value:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if host in {"ornek-site.com", "example.com", "your-domain.com", "your-username.github.io"}:
            value = ""
        elif parsed.scheme.lower() == "file":
            try:
                local_path = QUrl(value).toLocalFile()
                if not local_path or not Path(local_path).is_file():
                    value = ""
            except Exception:
                value = ""
    return value or _oss_update_find_local_manifest(self) or UPDATE_MANIFEST_URL


def _oss_update_save_source(self, url):
    self.data.setdefault("settings", {})["update_url"] = str(url or "").strip()
    try:
        self.save()
    except Exception:
        pass


def _oss_update_check_worker(self, url):
    import json as _json
    try:
        # Static hosts/CDNs can cache latest.json. Add a unique query parameter
        # for HTTP(S) requests so the app checks the current published manifest.
        request_url = url
        parsed_manifest_url = urlparse(url)
        if parsed_manifest_url.scheme.lower() in ("http", "https"):
            query_items = urllib.parse.parse_qsl(parsed_manifest_url.query, keep_blank_values=True)
            query_items = [(k, v) for k, v in query_items if k != "oss_update_check"]
            query_items.append(("oss_update_check", str(time.time_ns())))
            request_url = urllib.parse.urlunparse(parsed_manifest_url._replace(query=urllib.parse.urlencode(query_items)))
        req = urllib.request.Request(
            request_url,
            headers={
                "User-Agent": "OSS-Browser-Updater/2.0",
                "Accept": "application/json,text/plain,*/*",
                "Cache-Control": "no-cache, no-store, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
        with urllib.request.urlopen(req, timeout=UPDATE_CHECK_TIMEOUT) as response:
            raw = response.read().decode("utf-8-sig", "ignore")
        manifest = _json.loads(raw)
        version = str(manifest.get("version", "")).strip()
        download_url = str(manifest.get("download", "")).strip()
        if not version or not download_url:
            raise RuntimeError("Güncelleme manifesti eksik veya hatalı.")
        # Allow relative download paths, so the same website folder works locally and when hosted.
        download_url = urljoin(url, download_url)
        source_scheme = urlparse(url).scheme.lower()
        download_scheme = urlparse(download_url).scheme.lower()
        if source_scheme == "file" and download_scheme != "file":
            raise RuntimeError("Yerel file:/// manifest yalnızca yerel file:/// paketleri indirebilir.")
        if source_scheme in ("http", "https") and download_scheme not in ("http", "https"):
            raise RuntimeError("Web manifesti yalnızca HTTP(S) paket adresleri kullanabilir.")
        if download_scheme == "file":
            local_package = QUrl(download_url).toLocalFile()
            if not local_package or not Path(local_package).is_file():
                expected_path = local_package or download_url
                raise FileNotFoundError(
                    "latest.json bulundu ancak indirme ZIP'i belirtilen konumda yok:\n"
                    f"{expected_path}\n\n"
                    "Güncelleme merkezinde 'Site klasörüne otomatik kaydet' düğmesini kullan veya ZIP'i "
                    "latest.json dosyasının bir üst klasöründeki downloads klasörüne koy."
                )
        self._oss_update_result = {
            "type": "check",
            "ok": True,
            "version": version,
            "download": download_url,
            "notes": str(manifest.get("notes", "")).strip(),
            "required": bool(manifest.get("required", False)),
            "sha256": str(manifest.get("sha256", "")).strip().lower(),
        }
    except Exception as exc:
        # Give a useful explanation instead of exposing only urllib's low-level
        # Windows DNS error (for example: [Errno 11001] getaddrinfo failed).
        raw_error = str(exc)
        lowered = raw_error.lower()
        parsed = urlparse(url)
        if "getaddrinfo failed" in lowered or "11001" in lowered or "name or service not known" in lowered:
            friendly_error = (
                "Güncelleme sunucusunun adresi çözümlenemedi (DNS).\n\n"
                "OSS → Güncelleme Sitesini Ayarla menüsünden gerçek, yayımlanmış "
                "bir HTTPS adresi gir. Örnek: https://alan-adin.example/updates/latest.json\n\n"
                "Siteyi henüz yayımlamadıysan, index.html dosyasının bulunduğu klasördeki "
                "updates/latest.json dosyasının yerel file:/// adresini kullanabilirsin. "
                "index.html adresini değil latest.json adresini seç.\n\n"
                "Not: example/ornek-site gibi örnek alan adları çalışmaz."
            )
        elif parsed.scheme.lower() == "file":
            friendly_error = (
                "Yerel güncelleme dosyası açılamadı. RAR/Temp klasöründeki dosya silinmiş "
                "veya taşınmış olabilir. ZIP'i kalıcı bir klasöre çıkartıp "
                "updates/latest.json dosyasının yolunu yeniden ayarla.\n\nAyrıntı: " + raw_error
            )
        else:
            friendly_error = raw_error
        self._oss_update_result = {
            "type": "check",
            "ok": False,
            "error": friendly_error,
        }


def _oss_update_begin_check(self, silent=False):
    if getattr(self, "_oss_update_busy", False):
        return
    url = _oss_update_source(self)
    if not url:
        if silent:
            return
        url, ok = QInputDialog.getText(
            self,
            "OSS Browser Güncelleme Kaynağı",
            "latest.json adresini gir (index.html değil).\n\n" 
            "İnternette yayımladıysan HTTPS adresi kullan. Yerel test için ",
            text=UPDATE_MANIFEST_URL,
        )
        if not ok or not url.strip():
            return
        url = url.strip()
        _oss_update_save_source(self, url)

    parsed_update_url = urlparse(url)
    if parsed_update_url.scheme not in ("http", "https", "file") or (parsed_update_url.scheme == "file" and not url.startswith("file:///")):
        if not silent:
            QMessageBox.warning(self, "Güncelleme", "Adres https://, http:// veya bu bilgisayardaki bir file:///updates/latest.json yolu olmalı.")
        return
    if parsed_update_url.scheme == "file":
        local_path = QUrl(url).toLocalFile()
        if not local_path or not Path(local_path).is_file():
            if not silent:
                QMessageBox.warning(
                    self, "Güncelleme",
                    "latest.json dosyası bulunamadı.\n\n"
                    "RAR/Temp içindeki geçici yolu kullanma. ZIP paketini masaüstünde kalıcı bir klasöre çıkarıp "
                    "updates/latest.json dosyasını seç."
                )
            return
    if parsed_update_url.scheme in ("http", "https") and (parsed_update_url.hostname or "").lower() in {"ornek-site.com", "example.com", "your-domain.com", "your-username.github.io"}:
        if not silent:
            QMessageBox.warning(self, "Güncelleme", "Bu örnek adres gerçek bir site değil. Güncelleme siteni HTTPS ile yayımla ve gerçek latest.json adresini gir.")
        return

    self._oss_update_busy = True
    self._oss_update_silent = bool(silent)
    self._oss_update_result = None
    self.statusBar().showMessage("OSS Browser güncellemeleri denetleniyor...", 2500)
    threading.Thread(
        target=_oss_update_check_worker,
        args=(self, url),
        daemon=True,
        name="OSS-Update-Check",
    ).start()


def _oss_version_key(value):
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(x) for x in parts[:4]) if parts else (0,)


def _oss_update_download_worker(self, download_url, expected_sha256=""):
    temp_root = Path(tempfile.mkdtemp(prefix="oss_browser_update_"))
    zip_path = temp_root / "update.zip"
    extract_dir = temp_root / "package"
    try:
        parsed_download = urlparse(download_url)
        if parsed_download.scheme.lower() == "file":
            local_package = QUrl(download_url).toLocalFile()
            if not local_package or not Path(local_package).is_file():
                raise FileNotFoundError(
                    "Güncelleme ZIP'i bulunamadı. latest.json içindeki download adresini kontrol et.\n"
                    f"Aranan dosya: {local_package or download_url}\n"
                    "Yerel testte güncelleme merkezindeki 'Site klasörüne otomatik kaydet' düğmesini kullan."
                )
        request = urllib.request.Request(
            download_url,
            headers={"User-Agent": "OSS-Browser-Updater/2.0", "Cache-Control": "no-cache"},
        )
        with urllib.request.urlopen(request, timeout=30) as response, zip_path.open("wb") as out:
            shutil.copyfileobj(response, out)
        expected_sha256 = str(expected_sha256 or "").strip().lower()
        if expected_sha256:
            digest = hashlib.sha256()
            with zip_path.open("rb") as downloaded:
                for chunk in iter(lambda: downloaded.read(1024 * 1024), b""):
                    digest.update(chunk)
            actual_sha256 = digest.hexdigest().lower()
            if actual_sha256 != expected_sha256:
                raise RuntimeError("Güncelleme dosyasının SHA-256 özeti uyuşmuyor; güvenlik için kurulum iptal edildi.")
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as archive:
            for member in archive.infolist():
                name = Path(member.filename)
                if name.is_absolute() or ".." in name.parts:
                    raise RuntimeError("Güncelleme arşivinde geçersiz yol bulundu.")
            archive.extractall(extract_dir)

        candidates = list(extract_dir.rglob("oss_browser.py"))
        if not candidates:
            raise RuntimeError("Güncelleme paketinde oss_browser.py bulunamadı.")

        package_root = candidates[0].parent
        self._oss_update_result = {
            "type": "download",
            "ok": True,
            "package_root": str(package_root),
            "temp_root": str(temp_root),
        }
    except Exception as exc:
        shutil.rmtree(temp_root, ignore_errors=True)
        self._oss_update_result = {
            "type": "download",
            "ok": False,
            "error": str(exc),
        }


def _oss_update_start_download(self, download_url, expected_sha256=""):
    if getattr(self, "_oss_update_stage", "") == "download":
        return
    self._oss_update_stage = "download"
    self._oss_update_result = None
    self.statusBar().showMessage("Yeni OSS Browser sürümü indiriliyor...", 2500)
    threading.Thread(
        target=_oss_update_download_worker,
        args=(self, download_url, expected_sha256),
        daemon=True,
        name="OSS-Update-Download",
    ).start()


def _oss_update_apply(self, package_root):
    package_root = Path(package_root)
    current_script = Path(sys.argv[0]).resolve()
    target_dir = current_script.parent
    target_script = target_dir / current_script.name
    new_script = package_root / "oss_browser.py"
    if not new_script.exists():
        QMessageBox.critical(self, "Güncelleme", "Yeni oss_browser.py bulunamadı.")
        return

    updater = Path(tempfile.gettempdir()) / f"oss_browser_update_{int(time.time())}.bat"
    py_exe = Path(sys.executable).resolve()
    source_dir = str(package_root)
    dest_dir = str(target_dir)
    source_script = str(new_script)

    bat = f"""@echo off
setlocal
ping 127.0.0.1 -n 5 >nul
copy /Y "{source_script}" "{target_script}" >nul
if exist "{source_dir}\\requirements.txt" copy /Y "{source_dir}\\requirements.txt" "{dest_dir}\\requirements.txt" >nul
if exist "{source_dir}\\start.bat" copy /Y "{source_dir}\\start.bat" "{dest_dir}\\start.bat" >nul
if exist "{source_dir}\\tools\\pytub.exe" (
  if not exist "{dest_dir}\\tools" mkdir "{dest_dir}\\tools"
  copy /Y "{source_dir}\\tools\\pytub.exe" "{dest_dir}\\tools\\pytub.exe" >nul
)
if exist "{py_exe}" (
  start "" "{py_exe}" "{target_script}"
) else (
  start "" "{target_script}"
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Milliseconds 800; Remove-Item -LiteralPath '%~f0' -Force -ErrorAction SilentlyContinue"
endlocal
"""
    updater.write_text(bat, encoding="utf-8")
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", str(updater)],
            cwd=str(target_dir),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        QMessageBox.critical(self, "Güncelleme", f"Güncelleme başlatılamadı:\n{exc}")
        return
    self.statusBar().showMessage("Güncelleme hazırlanıyor. OSS Browser kapanacak...", 5000)
    QTimer.singleShot(800, QApplication.instance().quit)


def _oss_update_poll(self):
    result = getattr(self, "_oss_update_result", None)
    if not result:
        return
    self._oss_update_result = None
    stage = result.get("type")
    if stage == "check":
        self._oss_update_busy = False
        self._oss_update_stage = ""
        if not result.get("ok"):
            if not getattr(self, "_oss_update_silent", False):
                QMessageBox.warning(self, "Güncelleme", "Güncelleme kontrolü başarısız:\n" + result.get("error", "Bilinmeyen hata"))
            return
        latest = result.get("version", "0")
        if _oss_version_key(latest) <= _oss_version_key(APP_VERSION):
            if not getattr(self, "_oss_update_silent", False):
                QMessageBox.information(self, "Güncelleme", f"OSS Browser güncel.\nMevcut sürüm: {APP_VERSION}")
            return
        notes = result.get("notes", "")
        msg = f"Yeni OSS Browser sürümü bulundu: {latest}\nMevcut sürüm: {APP_VERSION}"
        if notes:
            msg += f"\n\n{notes}"
        answer = QMessageBox.question(
            self,
            "OSS Browser Güncellemesi",
            msg + "\n\nŞimdi indirip güncellemek ister misin?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._oss_update_busy = True
            _oss_update_start_download(self, result["download"], result.get("sha256", ""))
        return

    if stage == "download":
        self._oss_update_busy = False
        self._oss_update_stage = ""
        if not result.get("ok"):
            QMessageBox.critical(self, "Güncelleme", "Yeni sürüm indirilemedi:\n" + result.get("error", "Bilinmeyen hata"))
            return
        answer = QMessageBox.question(
            self,
            "Güncelleme Hazır",
            "Yeni sürüm indirildi. OSS Browser şimdi kapanıp yeni sürümü kuracak.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok,
        )
        if answer == QMessageBox.StandardButton.Ok:
            _oss_update_apply(self, result["package_root"])


def _oss_update_set_url(self):
    current = _oss_update_source(self)
    url, ok = QInputDialog.getText(
        self,
        "OSS Browser Güncelleme Sitesi",
        "latest.json adresi (index.html değil):\nHTTPS: https://site-adresin/updates/latest.json\nYerel: file:///C:/.../updates/latest.json",
        text=current or UPDATE_MANIFEST_URL,
    )
    if ok and url.strip():
        url = url.strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https", "file"):
            QMessageBox.warning(self, "Güncelleme", "Adres https://, http:// veya file:/// ile başlamalı.")
            return
        if parsed.scheme == "file":
            local_path = QUrl(url).toLocalFile()
            if not local_path or not Path(local_path).is_file():
                QMessageBox.warning(self, "Güncelleme", "Bu yolda latest.json bulunamadı. Önce site ZIP'ini kalıcı bir klasöre çıkart.")
                return
        if parsed.scheme in ("http", "https") and (parsed.hostname or "").lower() in {"ornek-site.com", "example.com", "your-domain.com", "your-username.github.io"}:
            QMessageBox.warning(self, "Güncelleme", "Örnek alan adı çalışmaz. Gerçek ve yayımlanmış sitenin adresini gir.")
            return
        _oss_update_save_source(self, url)
        QMessageBox.information(self, "Güncelleme", "Güncelleme adresi kaydedildi. Şimdi 'Güncellemeleri Denetle' seçeneğini kullan.")


def _oss_update_menu(self):
    if getattr(self, "_oss_update_menu_ready", False):
        return
    self._oss_update_menu_ready = True
    try:
        menu = self.menuBar().addMenu("OSS")
        check = menu.addAction(f"Güncellemeleri Denetle (v{APP_VERSION})")
        check.triggered.connect(lambda: _oss_update_begin_check(self, False))
        source = menu.addAction("Güncelleme Sitesini Ayarla")
        source.triggered.connect(lambda: _oss_update_set_url(self))
    except Exception:
        pass


_update_old_init = MainWindow.__init__
def _update_main_init(self, *args, **kwargs):
    _update_old_init(self, *args, **kwargs)
    try:
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
    except Exception:
        pass
    self._oss_update_result = None
    self._oss_update_busy = False
    self._oss_update_stage = ""
    self._oss_update_silent = True
    self._oss_update_timer = QTimer(self)
    self._oss_update_timer.setInterval(250)
    self._oss_update_timer.timeout.connect(lambda: _oss_update_poll(self))
    self._oss_update_timer.start()
    # Check on startup and periodically while the browser remains open.
    QTimer.singleShot(1800, lambda: _oss_update_begin_check(self, True))
    self._oss_update_auto_check_timer = QTimer(self)
    self._oss_update_auto_check_timer.setInterval(30 * 60 * 1000)
    self._oss_update_auto_check_timer.timeout.connect(
        lambda: _oss_update_begin_check(self, True) if not getattr(self, "_oss_update_busy", False) else None
    )
    self._oss_update_auto_check_timer.start()
    QTimer.singleShot(1200, lambda: _oss_update_menu(self))

MainWindow.__init__ = _update_main_init



# ============================================================
# OSS BROWSER v1.2.1 — ENGINE PICKER + MODERN TOOLBAR FIX
# ============================================================
# Search engine selection is available directly in the main toolbar and
# immediately updates persisted settings, home tabs, and address-bar searches.


def _oss_engine_name(browser):
    try:
        name = str(browser.data.get("settings", {}).get("search_engine", "Google"))
    except Exception:
        name = "Google"
    return name if name in SEARCH_ENGINES else "Google"


def _oss_sync_engine_picker(browser):
    picker = getattr(browser, "search_engine_combo", None)
    if picker is None:
        return
    current = _oss_engine_name(browser)
    try:
        picker.blockSignals(True)
        picker.setCurrentText(current)
    finally:
        picker.blockSignals(False)


def _oss_set_search_engine(browser, engine, show_message=True):
    engine = str(engine or "").strip()
    if engine not in SEARCH_ENGINES:
        engine = "Google"
    settings = browser.data.setdefault("settings", {})
    previous = settings.get("search_engine", "Google")
    settings["search_engine"] = engine
    try:
        browser.save()
    except Exception:
        pass
    _oss_sync_engine_picker(browser)
    # Keep an open Settings dialog synchronized too.
    dialog = getattr(browser, "settings_window", None)
    if dialog is not None:
        combo = getattr(dialog, "search_combo", None)
        if combo is not None:
            try:
                combo.blockSignals(True)
                combo.setCurrentText(engine)
            finally:
                combo.blockSignals(False)
    try:
        browser.refresh_home_pages()
    except Exception:
        pass
    if show_message:
        try:
            if previous != engine:
                browser.statusBar().showMessage(f"Varsayılan arama motoru değiştirildi: {engine}", 3500)
            else:
                browser.statusBar().showMessage(f"Seçili arama motoru: {engine}", 2200)
        except Exception:
            pass


def _oss_on_engine_picker_changed(self, engine):
    _oss_set_search_engine(self, engine)


# Re-style the browser after the original theme is applied. The active accent,
# dark/light palette, and existing V1-V5 controls remain intact.
_oss_base_apply_theme = MainWindow.apply_theme

def _oss_apply_theme_modern(self):
    _oss_base_apply_theme(self)
    settings = self.data.get("settings", {})
    dark = bool(settings.get("dark_mode", True))
    accent = str(settings.get("accent", "#7c5cff"))
    if accent not in {"#7c5cff", "#3b82f6", "#10b981", "#f97316", "#ef4444"}:
        accent = "#7c5cff"
    field = "#151c28" if dark else "#ffffff"
    panel = "#111827" if dark else "#ffffff"
    text = "#f4f7fb" if dark else "#1f2937"
    muted = "#93a0b5" if dark else "#667085"
    border = "#303c50" if dark else "#d4dbe5"
    hover = "#202a3a" if dark else "#edf2f7"
    self.setStyleSheet(self.styleSheet() + f"""
        QComboBox#SearchEngineSelector {{
            color: {text}; background: {field}; border: 1px solid {border};
            border-radius: 12px; padding: 7px 30px 7px 12px; min-width: 128px;
            min-height: 24px; font-size: 13px; font-weight: 700;
        }}
        QComboBox#SearchEngineSelector:hover {{ border-color: {accent}; background: {hover}; }}
        QComboBox#SearchEngineSelector:focus {{ border: 1px solid {accent}; }}
        QComboBox#SearchEngineSelector::drop-down {{
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 25px; border-left: 1px solid {border}; border-top-right-radius: 11px;
            border-bottom-right-radius: 11px;
        }}
        QComboBox#SearchEngineSelector QAbstractItemView {{
            color: {text}; background: {panel}; border: 1px solid {border};
            selection-background-color: {accent}; selection-color: #ffffff;
            outline: 0; padding: 5px;
        }}
        QLabel#SearchEngineLabel {{ color: {muted}; font-size: 10px; font-weight: 800; padding: 0 2px; }}
        QLineEdit#AddressBar {{ border-radius: 14px; padding-left: 15px; padding-right: 15px; }}
        QToolButton#SecurityBadge {{ border: 1px solid {border}; border-radius: 11px; padding: 5px 8px; }}
    """)

MainWindow.apply_theme = _oss_apply_theme_modern


# Add the engine picker next to the address bar without removing any existing
# browser actions. The selector is initialized before its signal is connected,
# so startup does not overwrite the saved preference.
_oss_base_setup_ui = MainWindow.setup_ui

def _oss_setup_ui_modern(self):
    _oss_base_setup_ui(self)
    try:
        self.url_bar.setObjectName("AddressBar")
        self.search_engine_label = QLabel("ARA")
        self.search_engine_label.setObjectName("SearchEngineLabel")
        self.search_engine_label.setToolTip("Adres çubuğu ve yeni sekme için varsayılan arama motoru")
        self.search_engine_combo = QComboBox()
        self.search_engine_combo.setObjectName("SearchEngineSelector")
        self.search_engine_combo.addItems(list(SEARCH_ENGINES.keys()))
        self.search_engine_combo.setToolTip(
            "Arama motorunu anında değiştirir. Seçim kaydedilir; ayarlara girmen gerekmez."
        )
        self.search_engine_combo.setMinimumContentsLength(11)
        self.search_engine_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.search_engine_combo.setCurrentText(_oss_engine_name(self))
        self.navigation_toolbar.insertWidget(self.bookmark_action, self.search_engine_label)
        self.navigation_toolbar.insertWidget(self.bookmark_action, self.search_engine_combo)
        self.search_engine_combo.currentTextChanged.connect(
            lambda engine, browser=self: _oss_on_engine_picker_changed(browser, engine)
        )
        self.apply_theme()
    except Exception as exc:
        try:
            self.statusBar().showMessage("Arama motoru seçici yüklenemedi: " + str(exc), 4000)
        except Exception:
            pass

MainWindow.setup_ui = _oss_setup_ui_modern


# Make address-bar routing independent from old helper behavior: typed URLs open
# directly, search phrases use exactly the selected engine, and NOVA stays local.
def _oss_navigate_final(self):
    text = str(self.url_bar.text() or "").strip()
    if not text:
        return
    view = self.current_view()
    if view is None:
        tab = self.new_tab()
        view = tab.view if isinstance(tab, BrowserTab) else None
    if view is None:
        return

    # Fully qualified URLs, local files, and clear host names should not become
    # search queries.
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", text):
        try:
            view.setUrl(QUrl(text))
            return
        except Exception:
            pass
    if _nova_looks_like_domain(text):
        view.setUrl(QUrl("https://" + text))
        return

    engine = _oss_engine_name(self)
    if engine == NOVA_SEARCH_NAME:
        self._nova_search(text, 1)
        return

    template = SEARCH_ENGINES.get(engine) or GOOGLE_SEARCH
    try:
        target = template.format(quote_plus(text))
    except Exception:
        target = GOOGLE_SEARCH.format(quote_plus(text))
    view.setUrl(QUrl(target))

MainWindow.navigate = _oss_navigate_final


# Keep Settings' selection synchronized with the main-toolbar picker when the
# user presses Apply or Save, while preserving the existing dialog behavior.
_oss_base_settings_apply = BrowserSettingsDialog.apply

def _oss_settings_apply_final(self):
    _oss_base_settings_apply(self)
    try:
        _oss_sync_engine_picker(self.browser)
        engine = _oss_engine_name(self.browser)
        combo = getattr(self, "search_combo", None)
        if combo is not None:
            combo.blockSignals(True)
            combo.setCurrentText(engine)
            combo.blockSignals(False)
    except Exception:
        pass

BrowserSettingsDialog.apply = _oss_settings_apply_final

# A saved choice that is no longer available is repaired once, not reset to
# Google every launch. Existing Google/Bing/DuckDuckGo/NOVA preferences persist.
_oss_base_main_init_final = MainWindow.__init__

def _oss_main_init_final(self, *args, **kwargs):
    _oss_base_main_init_final(self, *args, **kwargs)
    try:
        settings = self.data.setdefault("settings", {})
        engine = settings.get("search_engine", "Google")
        if engine not in SEARCH_ENGINES:
            settings["search_engine"] = "Google"
            self.save()
        _oss_sync_engine_picker(self)
        self.setWindowTitle(f"{APP_NAME} v1.2.1")
        self.resize(max(self.width(), 1280), max(self.height(), 760))
    except Exception:
        pass

MainWindow.__init__ = _oss_main_init_final
APP_VERSION = "7.0.0"
# ============================================================
# OSS BROWSER 1.3.0 — PAGE TOOLS, NOVA FILTERS, WORKSPACE
# ============================================================
# This extension deliberately builds on the existing browser classes so that
# tabs, bookmarks, profiles, download handling, privacy controls and backups stay.

class OSSNovaFiltersDialog(QDialog):
    """NOVA language, topic, recency and default-domain filters."""
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("NOVA Search — Arama Filtreleri")
        self.setMinimumSize(540, 430)
        self.resize(600, 470)
        root = QVBoxLayout(self)
        title = QLabel("NOVA Search filtreleri")
        title.setObjectName("SettingsTitle")
        root.addWidget(title)
        intro = QLabel("Bu filtreler yalnızca NOVA'nın kendi yerel indeksine uygulanır. Google, Bing ve DuckDuckGo seçimlerini etkilemez.")
        intro.setWordWrap(True)
        root.addWidget(intro)

        settings = browser.data.setdefault("settings", {})
        form = QFormLayout()
        self.language = QComboBox()
        for label, value in [
            ("Yalnızca Türkçe kaynaklar", "turkish_only"),
            ("Türkçe kaynakları önce göster", "turkish_first"),
            ("Tüm diller", "all"),
        ]:
            self.language.addItem(label, value)
        self._select_data(self.language, settings.get("nova_language_filter", "turkish_only"))
        form.addRow("Dil filtresi", self.language)

        self.category = QComboBox()
        for label, value in [
            ("Tüm konular", "all"),
            ("Teknoloji / dokümantasyon", "docs"),
            ("Kod ve yazılım", "code"),
            ("Oyunlar / Minecraft", "gaming"),
            ("Ansiklopedi", "wiki"),
            ("Haberler", "news"),
            ("Genel web", "web"),
        ]:
            self.category.addItem(label, value)
        self._select_data(self.category, settings.get("nova_category_filter", "all"))
        form.addRow("Konu", self.category)

        self.recency = QComboBox()
        for label, value in [
            ("Tüm dizin kayıtları", "any"),
            ("Son 7 günde dizine eklenenler", "week"),
            ("Son 30 günde dizine eklenenler", "month"),
        ]:
            self.recency.addItem(label, value)
        self._select_data(self.recency, settings.get("nova_recency_filter", "any"))
        form.addRow("Dizin tarihi", self.recency)

        self.site = QLineEdit(str(settings.get("nova_default_site_filter", "")))
        self.site.setPlaceholderText("Örn. python.org — boş bırakılırsa tüm siteler")
        form.addRow("Varsayılan site filtresi", self.site)
        root.addLayout(form)

        help_text = QLabel("Ek sorgu operatörleri: site:python.org, intitle:kurulum ve \"tam ifade\". Dizin tarihi, sayfanın yayımlandığı tarihi değil, NOVA dizinine eklenme zamanını ifade eder.")
        help_text.setWordWrap(True)
        help_text.setObjectName("MutedLabel")
        root.addWidget(help_text)
        root.addStretch(1)
        buttons = QHBoxLayout()
        reset = QPushButton("Varsayılana dön")
        save = QPushButton("Filtreleri kaydet")
        close = QPushButton("Kapat")
        reset.clicked.connect(self.reset_defaults)
        save.clicked.connect(self.save_filters)
        close.clicked.connect(self.reject)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        buttons.addWidget(save)
        buttons.addWidget(close)
        root.addLayout(buttons)

    @staticmethod
    def _select_data(combo, value):
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def reset_defaults(self):
        self._select_data(self.language, "turkish_only")
        self._select_data(self.category, "all")
        self._select_data(self.recency, "any")
        self.site.clear()

    def save_filters(self):
        raw_site = self.site.text().strip().lower()
        raw_site = re.sub(r"^https?://", "", raw_site).split("/", 1)[0].strip().strip(".")
        if raw_site and not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", raw_site):
            QMessageBox.warning(self, "Geçersiz site", "Site alanına yalnızca alan adı yaz. Örnek: python.org")
            return
        settings = self.browser.data.setdefault("settings", {})
        settings["nova_language_filter"] = str(self.language.currentData() or "turkish_only")
        settings["nova_category_filter"] = str(self.category.currentData() or "all")
        settings["nova_recency_filter"] = str(self.recency.currentData() or "any")
        settings["nova_default_site_filter"] = raw_site
        self.browser.save()
        self.browser.statusBar().showMessage("NOVA arama filtreleri kaydedildi.", 3000)
        self.accept()


class OSSReaderDialog(QDialog):
    def __init__(self, browser, title, text):
        super().__init__(browser)
        self.browser = browser
        self.reader_title = str(title or "Okuma modu")
        self.reader_text = str(text or "")
        self.setWindowTitle("OSS Okuma Modu — " + self.reader_title[:100])
        self.resize(900, 720)
        root = QVBoxLayout(self)
        header = QLabel(self.reader_title)
        header.setObjectName("SettingsTitle")
        header.setWordWrap(True)
        root.addWidget(header)
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(False)
        self.body.setPlainText(self.reader_text)
        self.body.setStyleSheet("QTextBrowser { border: 0; padding: 22px; font-size: 16px; line-height: 1.7; }")
        root.addWidget(self.body, 1)
        controls = QHBoxLayout()
        copy_btn = QPushButton("Metni kopyala")
        save_btn = QPushButton("TXT olarak kaydet")
        smaller = QPushButton("A−")
        larger = QPushButton("A+")
        close_btn = QPushButton("Kapat")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.reader_title + "\n\n" + self.reader_text))
        save_btn.clicked.connect(self.save_text)
        smaller.clicked.connect(lambda: self._change_font(-1))
        larger.clicked.connect(lambda: self._change_font(1))
        close_btn.clicked.connect(self.accept)
        for widget in (copy_btn, save_btn, smaller, larger):
            controls.addWidget(widget)
        controls.addStretch(1)
        controls.addWidget(close_btn)
        root.addLayout(controls)
        self._font_size = 16

    def _change_font(self, delta):
        self._font_size = max(10, min(30, self._font_size + delta))
        self.body.setStyleSheet(f"QTextBrowser {{ border: 0; padding: 22px; font-size: {self._font_size}px; line-height: 1.7; }}")

    def save_text(self):
        path, _ = QFileDialog.getSaveFileName(self, "Okuma metnini kaydet", str(Path.home() / "oss-okuma.txt"), "Metin dosyası (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(self.reader_title + "\n\n" + self.reader_text, encoding="utf-8")
            QMessageBox.information(self, "OSS Browser", "Metin dosyası kaydedildi.")
        except Exception as exc:
            QMessageBox.warning(self, "Kaydetme hatası", str(exc))


class OSSPageToolsDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS — Sayfa Araçları")
        self.setMinimumWidth(510)
        self.resize(560, 500)
        root = QVBoxLayout(self)
        title = QLabel("Sayfa araçları")
        title.setObjectName("SettingsTitle")
        root.addWidget(title)
        info = QLabel("Geçerli web sayfasında okuma, metin, ekran görüntüsü, PDF, çeviri ve ses araçlarını kullan.")
        info.setWordWrap(True)
        root.addWidget(info)
        grid = QVBoxLayout()
        rows = [
            ("Okuma modunu aç", self.reader_mode),
            ("Sayfa görüntüsünü PNG olarak kaydet", self.save_screenshot),
            ("Sayfayı PDF olarak kaydet", self.save_pdf),
            ("Sayfa metnini panoya kopyala", self.copy_text),
            ("Sayfa metnini TXT olarak kaydet", self.save_text),
            ("Sayfayı Türkçeye çevir", self.translate_page),
            ("Sayfayı sesli oku", self.read_aloud),
            ("Sesli okumayı durdur", self.stop_read_aloud),
            ("Sayfada metin bul", self.find_text),
            ("Yakınlaştır / uzaklaştır", self.zoom_dialog),
        ]
        for text, callback in rows:
            button = QPushButton(text)
            button.setMinimumHeight(36)
            button.clicked.connect(callback)
            grid.addWidget(button)
        root.addLayout(grid)
        root.addStretch(1)
        close = QPushButton("Kapat")
        close.clicked.connect(self.accept)
        root.addWidget(close)

    def _view(self):
        view = self.browser.current_view()
        if view is None:
            QMessageBox.information(self, "OSS Browser", "Önce bir web sayfası aç.")
        return view

    @staticmethod
    def _extract_script():
        return r'''JSON.stringify((function(){
          const title=(document.title||location.href||"Sayfa").trim();
          const root=(document.querySelector('article')||document.querySelector('main')||document.body);
          if(!root) return {title:title,text:"Sayfa metni bulunamadı."};
          const clone=root.cloneNode(true);
          clone.querySelectorAll('script,style,noscript,nav,header,footer,aside,form,button,iframe,svg,[aria-hidden="true"]').forEach(e=>e.remove());
          const text=(clone.innerText||clone.textContent||"").replace(/\n{3,}/g,"\n\n").trim();
          return {title:title,text:text.slice(0,60000)};
        })())'''

    def _with_page_text(self, callback):
        view = self._view()
        if not view:
            return
        view.page().runJavaScript(self._extract_script(), lambda result: self._unpack_page_text(result, callback))

    def _unpack_page_text(self, result, callback):
        try:
            if isinstance(result, str):
                obj = json.loads(result)
            elif isinstance(result, dict):
                obj = result
            else:
                obj = {}
            callback(str(obj.get("title", "Sayfa")), str(obj.get("text", "")))
        except Exception as exc:
            QMessageBox.warning(self, "Sayfa metni", "Sayfa metni alınamadı: " + str(exc))

    def reader_mode(self):
        self._with_page_text(lambda title, text: OSSReaderDialog(self.browser, title, text).exec())

    def copy_text(self):
        def done(title, text):
            QApplication.clipboard().setText(title + "\n\n" + text)
            self.browser.statusBar().showMessage("Sayfa metni panoya kopyalandı.", 2500)
        self._with_page_text(done)

    def save_text(self):
        def done(title, text):
            safe_name = re.sub(r"[^A-Za-z0-9ğüşöçıİĞÜŞÖÇ _-]+", "_", title).strip()[:70] or "sayfa"
            path, _ = QFileDialog.getSaveFileName(self, "Sayfa metnini kaydet", str(Path.home() / (safe_name + ".txt")), "Metin dosyası (*.txt)")
            if not path:
                return
            try:
                Path(path).write_text(title + "\n\n" + text, encoding="utf-8")
                QMessageBox.information(self, "OSS Browser", "Sayfa metni TXT olarak kaydedildi.")
            except Exception as exc:
                QMessageBox.warning(self, "Kaydetme hatası", str(exc))
        self._with_page_text(done)

    def save_screenshot(self):
        view = self._view()
        if not view:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Sayfa görüntüsünü kaydet", str(Path.home() / "oss-sayfa.png"), "PNG görüntüsü (*.png)")
        if not path:
            return
        try:
            ok = view.grab().save(path, "PNG")
            if ok:
                QMessageBox.information(self, "OSS Browser", "Görünür sayfa alanının ekran görüntüsü kaydedildi.")
            else:
                QMessageBox.warning(self, "OSS Browser", "Ekran görüntüsü kaydedilemedi.")
        except Exception as exc:
            QMessageBox.warning(self, "Ekran görüntüsü", str(exc))

    def save_pdf(self):
        view = self._view()
        if not view:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Sayfayı PDF kaydet", str(Path.home() / "oss-sayfa.pdf"), "PDF dosyası (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            view.page().printToPdf(path)
            self.browser.statusBar().showMessage("PDF oluşturma isteği gönderildi; dosyanın oluşması sayfanın boyutuna bağlıdır.", 4500)
        except Exception as exc:
            QMessageBox.warning(self, "PDF", "Bu PySide6 sürümünde PDF kaydı başarısız oldu: " + str(exc))

    def translate_page(self):
        view = self._view()
        if not view:
            return
        url = view.url().toString()
        if not url.startswith(("http://", "https://")):
            QMessageBox.information(self, "Çeviri", "Önce normal bir web sayfası aç.")
            return
        target, ok = QInputDialog.getItem(self, "Çeviri dili", "Hedef dil", ["Türkçe", "İngilizce", "Almanca", "Fransızca", "İspanyolca", "Arapça"], 0, False)
        if not ok:
            return
        language_codes = {"Türkçe": "tr", "İngilizce": "en", "Almanca": "de", "Fransızca": "fr", "İspanyolca": "es", "Arapça": "ar"}
        target_code = language_codes.get(target, "tr")
        self.browser.new_tab("https://translate.google.com/translate?sl=auto&tl=" + target_code + "&u=" + quote_plus(url))

    def read_aloud(self):
        view = self._view()
        if not view:
            return
        js = r'''(()=>{try{speechSynthesis.cancel();const root=document.querySelector('article')||document.querySelector('main')||document.body;const text=(root?.innerText||'').trim().slice(0,16000);if(!text){return 'Sayfa metni yok';}const u=new SpeechSynthesisUtterance(text);u.lang='tr-TR';u.rate=1;speechSynthesis.speak(u);return 'Sesli okuma başlatıldı';}catch(e){return 'Sesli okuma başlatılamadı';}})()'''
        view.page().runJavaScript(js, lambda result: self.browser.statusBar().showMessage(str(result or "Sesli okuma isteği gönderildi."), 3000))

    def stop_read_aloud(self):
        view = self._view()
        if view:
            view.page().runJavaScript("try{speechSynthesis.cancel();'Sesli okuma durduruldu';}catch(e){'Ses durdurulamadı';}", lambda result: self.browser.statusBar().showMessage(str(result or "Sesli okuma durduruldu."), 2500))

    def find_text(self):
        view = self._view()
        if not view:
            return
        value, ok = QInputDialog.getText(self, "Sayfada bul", "Aranacak metin:")
        if ok and value.strip():
            view.findText(value.strip())

    def zoom_dialog(self):
        view = self._view()
        if not view:
            return
        current = int(round(view.zoomFactor() * 100))
        value, ok = QInputDialog.getInt(self, "Sayfa yakınlaştırma", "Yakınlaştırma yüzdesi", current, 50, 250, 10)
        if ok:
            view.setZoomFactor(value / 100.0)


def _oss_v6_reader(browser):
    view = browser.current_view()
    if view is None:
        browser.statusBar().showMessage("Önce bir web sayfası aç.", 2200)
        return
    tool = OSSPageToolsDialog(browser)
    view.page().runJavaScript(tool._extract_script(), lambda result: tool._unpack_page_text(
        result, lambda title, text: OSSReaderDialog(browser, title, text).exec()
    ))
    # Keep the helper alive until the asynchronous JavaScript callback arrives.
    browser._oss_v6_reader_helper = tool


def _oss_v6_open_page_tools(browser):
    OSSPageToolsDialog(browser).exec()


def _oss_v6_open_nova_filters(browser):
    OSSNovaFiltersDialog(browser).exec()


def _oss_v6_reopen_closed_tab(browser):
    closed = getattr(browser, "closed_tabs", None)
    if not closed:
        browser.statusBar().showMessage("Geri açılacak kapalı sekme yok.", 2500)
        return
    try:
        item = closed.pop(0)
        if isinstance(item, (list, tuple)):
            url = str(item[0] or "")
            private = bool(item[1]) if len(item) > 1 else False
        elif isinstance(item, dict):
            url = str(item.get("url", ""))
            private = bool(item.get("private", False))
        else:
            url, private = str(item), False
        if url and url not in ("about:blank", HOME_URL):
            browser.new_tab(url, private=private)
            browser.statusBar().showMessage("Kapalı sekme geri açıldı.", 2200)
        else:
            browser.statusBar().showMessage("Son kapatılan sekmenin adresi bulunamadı.", 2500)
    except Exception as exc:
        browser.statusBar().showMessage("Sekme geri açılamadı: " + str(exc), 3500)
    try:
        browser.save()
    except Exception:
        pass


def _oss_v6_toggle_pin(browser):
    tab = browser.current_tab()
    if not isinstance(tab, BrowserTab):
        return
    tab.pinned = not bool(getattr(tab, "pinned", False))
    browser.tab_title_changed(tab, tab.view.title().strip() or "Yeni Sekme")
    if tab.pinned:
        index = browser.tabs.indexOf(tab)
        if index > 0:
            browser.tabs.removeTab(index)
            index = browser.tabs.insertTab(0, tab, "📌 " + (tab.view.title().strip() or "Sekme")[:25])
            browser.tabs.setCurrentIndex(index)
        browser.statusBar().showMessage("Sekme sabitlendi.", 2200)
    else:
        browser.statusBar().showMessage("Sekme sabitlemesi kaldırıldı.", 2200)
    try:
        browser.save()
    except Exception:
        pass


def _oss_v6_duplicate_tab(browser):
    tab = browser.current_tab()
    if isinstance(tab, BrowserTab):
        url = tab.view.url().toString()
        browser.new_tab(url if url and url != "about:blank" else None, private=bool(tab.private))


def _oss_v6_toggle_mute(browser):
    tab = browser.current_tab()
    if not isinstance(tab, BrowserTab):
        return
    try:
        muted = not bool(tab.view.page().isAudioMuted())
        tab.view.page().setAudioMuted(muted)
        browser.statusBar().showMessage("Sekme sesi " + ("kapatıldı." if muted else "açıldı."), 2200)
    except Exception as exc:
        browser.statusBar().showMessage("Sekme sesi değiştirilemedi: " + str(exc), 3000)


def _oss_v6_copy_current_url(browser):
    view = browser.current_view()
    if view:
        QApplication.clipboard().setText(view.url().toString())
        browser.statusBar().showMessage("Sayfa adresi panoya kopyalandı.", 2200)


def _oss_v6_open_in_system_browser(browser):
    view = browser.current_view()
    if view:
        url = view.url()
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)


def _oss_v6_open_command_center(browser):
    dlg = QDialog(browser)
    dlg.setWindowTitle("OSS Browser — Çalışma Merkezi")
    dlg.resize(760, 540)
    root = QVBoxLayout(dlg)
    title = QLabel("OSS Çalışma Merkezi")
    title.setObjectName("SettingsTitle")
    root.addWidget(title)
    desc = QLabel("Arama, sayfa araçları, gizlilik, sekmeler, profiller ve yedekleme özellikleri tek yerde.")
    desc.setWordWrap(True)
    root.addWidget(desc)
    grid = QHBoxLayout()
    columns = [QVBoxLayout(), QVBoxLayout(), QVBoxLayout()]
    actions = [
        ("Sayfa Araçları", lambda: _oss_v6_open_page_tools(browser)),
        ("NOVA Arama Filtreleri", lambda: _oss_v6_open_nova_filters(browser)),
        ("Kapalı Sekmeyi Geri Aç", lambda: _oss_v6_reopen_closed_tab(browser)),
        ("Sekme Grupları", lambda: browser.open_tab_groups()),
        ("Oturumlar", lambda: browser.open_sessions()),
        ("Sekme Ara", lambda: browser.open_tab_search()),
        ("Güvenlik Merkezi", lambda: browser.open_security_center()),
        ("Gizlilik Merkezi", lambda: browser.open_privacy_center()),
        ("Performans Merkezi", lambda: V5PerformanceDialog(browser).exec()),
        ("Profil Yönetimi", lambda: browser.open_profiles()),
        ("Tema Merkezi", lambda: browser.open_theme_center()),
        ("YouTube Araçları", lambda: _v5_open_youtube(browser)),
        ("OSS AI Paneli", lambda: browser.toggle_ai_panel()),
        ("Yedekleme / Geri Yükleme", lambda: _v5_open_backup(browser)),
        ("Sekmeyi Sabitle / Çöz", lambda: _oss_v6_toggle_pin(browser)),
        ("Mevcut Sekmeyi Kopyala", lambda: _oss_v6_duplicate_tab(browser)),
        ("Sekme Sesini Aç / Kapat", lambda: _oss_v6_toggle_mute(browser)),
        ("Siteyi Sistem Tarayıcısında Aç", lambda: _oss_v6_open_in_system_browser(browser)),
    ]
    for i, (label, callback) in enumerate(actions):
        button = QPushButton(label)
        button.setMinimumHeight(36)
        button.clicked.connect(lambda checked=False, cb=callback: cb())
        columns[i % 3].addWidget(button)
    for column in columns:
        column.addStretch(1)
        grid.addLayout(column, 1)
    root.addLayout(grid)
    close = QPushButton("Kapat")
    close.clicked.connect(dlg.accept)
    root.addWidget(close)
    dlg.exec()


def _oss_v6_take_screenshot(browser):
    view = browser.current_view()
    if view is None:
        browser.statusBar().showMessage("Önce bir web sayfası aç.", 2200)
        return
    path, _ = QFileDialog.getSaveFileName(browser, "Görünür sayfa alanını kaydet", str(Path.home() / "oss-sayfa.png"), "PNG görüntüsü (*.png)")
    if not path:
        return
    try:
        if view.grab().save(path, "PNG"):
            browser.statusBar().showMessage("Ekran görüntüsü kaydedildi.", 2500)
        else:
            QMessageBox.warning(browser, "OSS Browser", "Ekran görüntüsü kaydedilemedi.")
    except Exception as exc:
        QMessageBox.warning(browser, "OSS Browser", "Ekran görüntüsü kaydedilemedi: " + str(exc))


def _oss_v6_add_shortcut(browser, text, shortcut, callback):
    action = QAction(text, browser)
    action.setShortcut(QKeySequence(shortcut))
    action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    action.triggered.connect(callback)
    browser.addAction(action)
    if not hasattr(browser, "_oss_v6_shortcuts"):
        browser._oss_v6_shortcuts = []
    browser._oss_v6_shortcuts.append(action)
    return action


_oss_v6_old_setup_ui = MainWindow.setup_ui

def _oss_v6_setup_ui(self):
    _oss_v6_old_setup_ui(self)
    # Add a compact tools menu without removing existing toolbar buttons.
    try:
        self.tools_button = QToolButton(self)
        self.tools_button.setText("Araçlar")
        self.tools_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.tools_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.tools_button)
        menu.addAction("OSS Çalışma Merkezi", lambda: _oss_v6_open_command_center(self))
        menu.addAction("Sayfa Araçları", lambda: _oss_v6_open_page_tools(self))
        menu.addAction("Okuma Modu", lambda: _oss_v6_reader(self))
        menu.addAction("NOVA Arama Filtreleri", lambda: _oss_v6_open_nova_filters(self))
        menu.addSeparator()
        menu.addAction("Kapalı Sekmeyi Geri Aç", lambda: _oss_v6_reopen_closed_tab(self))
        menu.addAction("Sekmeyi Sabitle / Sabitlemeyi Kaldır", lambda: _oss_v6_toggle_pin(self))
        menu.addAction("Mevcut Sekmeyi Kopyala", lambda: _oss_v6_duplicate_tab(self))
        menu.addAction("Sekme Sesini Aç / Kapat", lambda: _oss_v6_toggle_mute(self))
        menu.addAction("Sayfa Adresini Kopyala", lambda: _oss_v6_copy_current_url(self))
        menu.addAction("Sistem Tarayıcısında Aç", lambda: _oss_v6_open_in_system_browser(self))
        self.tools_button.setMenu(menu)
        self.navigation_toolbar.insertWidget(self.bookmark_action, self.tools_button)
    except Exception as exc:
        try:
            self.statusBar().showMessage("Araçlar menüsü oluşturulamadı: " + str(exc), 3500)
        except Exception:
            pass
    try:
        menu = self.more_button.menu()
        if menu is not None:
            menu.addSeparator()
            v6menu = menu.addMenu("OSS 1.3 — Gelişmiş")
            v6menu.addAction("Çalışma Merkezi", lambda: _oss_v6_open_command_center(self))
            v6menu.addAction("NOVA Arama Filtreleri", lambda: _oss_v6_open_nova_filters(self))
            v6menu.addAction("Sayfa Araçları", lambda: _oss_v6_open_page_tools(self))
            v6menu.addAction("Okuma Modu", lambda: _oss_v6_reader(self))
            v6menu.addAction("Kapalı Sekmeyi Geri Aç", lambda: _oss_v6_reopen_closed_tab(self))
    except Exception:
        pass
    _oss_v6_add_shortcut(self, "Kapalı Sekmeyi Geri Aç", "Ctrl+Shift+T", lambda: _oss_v6_reopen_closed_tab(self))
    _oss_v6_add_shortcut(self, "Okuma Modu", "Ctrl+Shift+R", lambda: _oss_v6_reader(self))
    _oss_v6_add_shortcut(self, "Sayfa Araçları", "Ctrl+Shift+P", lambda: _oss_v6_open_page_tools(self))
    _oss_v6_add_shortcut(self, "NOVA Filtreleri", "Ctrl+Shift+F", lambda: _oss_v6_open_nova_filters(self))
    _oss_v6_add_shortcut(self, "Ekran Görüntüsü Kaydet", "Ctrl+Shift+S", lambda: _oss_v6_take_screenshot(self))
    _oss_v6_add_shortcut(self, "OSS Çalışma Merkezi", "Ctrl+Shift+O", lambda: _oss_v6_open_command_center(self))

MainWindow.setup_ui = _oss_v6_setup_ui

# More polished browser chrome while preserving the current accent/theme settings.
_oss_v6_old_apply_theme = MainWindow.apply_theme

def _oss_v6_apply_theme(self):
    _oss_v6_old_apply_theme(self)
    try:
        settings = self.data.get("settings", {})
        dark = bool(settings.get("dark_mode", True))
        accent = str(settings.get("accent", "#7c5cff"))
        background = "#0b1019" if dark else "#f4f6fa"
        panel = "#111a27" if dark else "#ffffff"
        text = "#edf2fa" if dark else "#1c2635"
        border = "#2a3548" if dark else "#d7deea"
        hover = "#202c40" if dark else "#e9eef7"
        self.setStyleSheet(self.styleSheet() + f"""
            QToolBar {{ spacing: 5px; padding: 6px 8px; border: 0; background: {background}; }}
            QToolButton {{ border: 1px solid transparent; border-radius: 10px; padding: 7px 9px; color: {text}; }}
            QToolButton:hover {{ background: {hover}; border-color: {border}; }}
            QToolButton:pressed {{ background: {accent}; color: white; }}
            QTabWidget::pane {{ border: 1px solid {border}; border-radius: 10px; top: -1px; }}
            QTabBar::tab {{ background: {panel}; color: {text}; padding: 9px 13px; margin: 2px 2px 0 2px; border: 1px solid {border}; border-bottom: 0; border-top-left-radius: 9px; border-top-right-radius: 9px; }}
            QTabBar::tab:selected {{ background: {accent}; color: white; border-color: {accent}; }}
            QTabBar::tab:hover:!selected {{ background: {hover}; }}
            QPushButton {{ border: 1px solid {border}; border-radius: 9px; padding: 8px 12px; }}
            QPushButton:hover {{ border-color: {accent}; background: {hover}; }}
            QLineEdit {{ border-radius: 10px; border: 1px solid {border}; padding: 8px 10px; }}
            QLineEdit:focus {{ border: 1px solid {accent}; }}
            QLabel#MutedLabel {{ color: {'#9aa8bd' if dark else '#667085'}; }}
        """)
    except Exception:
        pass

MainWindow.apply_theme = _oss_v6_apply_theme

# Expose feature methods to the existing command center/menu API.
MainWindow.open_nova_filters = _oss_v6_open_nova_filters
MainWindow.open_page_tools = _oss_v6_open_page_tools
MainWindow.open_workspace_center = _oss_v6_open_command_center
MainWindow.reopen_closed_tab = _oss_v6_reopen_closed_tab
MainWindow.toggle_pin_current_tab = _oss_v6_toggle_pin
MainWindow.duplicate_current_tab = _oss_v6_duplicate_tab
MainWindow.toggle_current_tab_mute = _oss_v6_toggle_mute

# Version label and window title.
APP_VERSION = "7.0.0"
_old_v6_main_init = MainWindow.__init__
def _oss_v6_main_init(self, *args, **kwargs):
    _old_v6_main_init(self, *args, **kwargs)
    try:
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(max(self.width(), 1320), max(self.height(), 780))
    except Exception:
        pass
MainWindow.__init__ = _oss_v6_main_init

\

# ============================================================================
# OSS BROWSER 1.4 — Ek çalışma araçları
# Çalışma alanları • Notlar • Bölünmüş ekran • Hızlı komutlar • QR • Site bilgisi
# Kişiselleştirilebilir başlangıç sayfası • NOVA yönetimi • Görev yöneticisi
# ============================================================================

class OSSNotesDialog(QDialog):
    """Kalıcı yerel not defteri; notlar data.json içinde saklanır."""
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Not Defteri")
        self.resize(850, 560)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Notların bilgisayarında yerel olarak saklanır."))
        split = QSplitter(Qt.Orientation.Horizontal)
        self.items = QListWidget()
        self.items.currentRowChanged.connect(self._load_row)
        split.addWidget(self.items)
        editor_box = QWidget()
        ed = QVBoxLayout(editor_box)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Not başlığı")
        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlaceholderText("Notunu yaz...")
        ed.addWidget(self.title_edit)
        ed.addWidget(self.body_edit, 1)
        split.addWidget(editor_box)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)
        row = QHBoxLayout()
        for label, fn in [("Yeni", self.new_note), ("Kaydet", self.save_note), ("Sil", self.delete_note), ("Bu sayfadan not oluştur", self.from_page)]:
            b = QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(1)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); row.addWidget(close)
        root.addLayout(row)
        self.refresh()

    def _notes(self):
        value = self.browser.data.setdefault("notes", [])
        if not isinstance(value, list):
            self.browser.data["notes"] = []
        return self.browser.data["notes"]

    def refresh(self, selected=0):
        self.items.blockSignals(True)
        self.items.clear()
        for note in self._notes():
            title = str(note.get("title") or "Adsız not").strip() or "Adsız not"
            self.items.addItem(title)
        self.items.blockSignals(False)
        if self.items.count():
            self.items.setCurrentRow(min(max(selected, 0), self.items.count() - 1))
        else:
            self.title_edit.clear(); self.body_edit.clear()

    def _load_row(self, row):
        notes = self._notes()
        if 0 <= row < len(notes):
            self.title_edit.setText(str(notes[row].get("title", "")))
            self.body_edit.setPlainText(str(notes[row].get("body", "")))

    def new_note(self):
        self.items.clearSelection(); self.items.setCurrentRow(-1)
        self.title_edit.clear(); self.body_edit.clear(); self.title_edit.setFocus()

    def save_note(self):
        title = self.title_edit.text().strip() or "Adsız not"
        body = self.body_edit.toPlainText()
        notes = self._notes(); row = self.items.currentRow()
        value = {"title": title, "body": body, "updated": datetime.now().isoformat(timespec="seconds"), "url": self.browser.current_view().url().toString() if self.browser.current_view() else ""}
        if 0 <= row < len(notes): notes[row] = value
        else: notes.insert(0, value); row = 0
        self.browser.save(); self.refresh(row)
        self.browser.statusBar().showMessage("Not kaydedildi.", 1800)

    def delete_note(self):
        row = self.items.currentRow(); notes = self._notes()
        if 0 <= row < len(notes):
            del notes[row]; self.browser.save(); self.refresh(max(row - 1, 0))

    def from_page(self):
        view = self.browser.current_view()
        if not view: return
        self.title_edit.setText(view.title() or "Sayfa notu")
        self.body_edit.setPlainText("Sayfa: " + view.url().toString() + "\n\n")
        self.body_edit.setFocus()


class OSSWorkspacesDialog(QDialog):
    """Ayrı sekme gruplarını kaydeden ve geri yükleyen çalışma alanları."""
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Çalışma Alanları")
        self.resize(620, 470)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Oyun, okul, yazılım gibi farklı sekme düzenlerini ayrı ayrı sakla."))
        self.list = QListWidget(); root.addWidget(self.list, 1)
        row = QHBoxLayout()
        for label, fn in [("Bu alanı kaydet", self.save_current), ("Aç / geçiş yap", self.switch), ("Yeni alan", self.create), ("Adını değiştir", self.rename), ("Sil", self.delete)]:
            b = QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
        root.addLayout(row)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); root.addWidget(close)
        browser.data.setdefault("workspaces", {})
        browser.data.setdefault("settings", {}).setdefault("active_workspace", "Genel")
        self.refresh()

    def _workspaces(self):
        value = self.browser.data.setdefault("workspaces", {})
        if not isinstance(value, dict): self.browser.data["workspaces"] = {}
        return self.browser.data["workspaces"]

    def _snapshot(self):
        result = []
        for i in range(self.browser.tabs.count()):
            tab = self.browser.tabs.widget(i)
            if not isinstance(tab, BrowserTab) or tab.private: continue
            url = tab.view.url().toString()
            if not url or url.startswith(("about:", "data:", "https://ossbrowser.local/home")): continue
            result.append({"url": url, "pinned": bool(getattr(tab, "pinned", False))})
        return result[:40]

    def refresh(self, select=None):
        self.list.clear()
        names = list(self._workspaces())
        active = self.browser.data.setdefault("settings", {}).get("active_workspace", "Genel")
        for name in names:
            count = len(self._workspaces().get(name, []))
            self.list.addItem(f"{'● ' if name == active else ''}{name}  ·  {count} sekme")
        if select and names:
            for i, name in enumerate(names):
                if name == select: self.list.setCurrentRow(i); break
        elif self.list.count(): self.list.setCurrentRow(0)

    def _selected_name(self):
        item = self.list.currentItem()
        if not item: return ""
        return item.text().removeprefix("● ").split("  ·  ")[0].strip()

    def save_current(self):
        name = self.browser.data.setdefault("settings", {}).get("active_workspace", "Genel")
        self._workspaces()[name] = self._snapshot(); self.browser.save(); self.refresh(name)
        self.browser.statusBar().showMessage(f"Çalışma alanı kaydedildi: {name}", 2200)

    def create(self):
        name, ok = QInputDialog.getText(self, "Yeni çalışma alanı", "Ad:", text="Yeni çalışma alanı")
        name = name.strip()
        if not ok or not name: return
        if name in self._workspaces():
            QMessageBox.information(self, "Çalışma alanları", "Bu ad zaten var."); return
        self._workspaces()[name] = self._snapshot()
        self.browser.data.setdefault("settings", {})["active_workspace"] = name
        self.browser.save(); self.refresh(name)

    def switch(self):
        name = self._selected_name()
        if not name: return
        settings = self.browser.data.setdefault("settings", {})
        old = settings.get("active_workspace", "Genel")
        self._workspaces()[old] = self._snapshot()
        urls = self._workspaces().get(name, [])
        # Remove all existing tab widgets, then reconstruct the chosen workspace.
        for i in range(self.browser.tabs.count() - 1, -1, -1):
            widget = self.browser.tabs.widget(i)
            self.browser.tabs.removeTab(i)
            if widget is not None: widget.deleteLater()
        settings["active_workspace"] = name
        if not urls:
            self.browser.new_tab()
        else:
            for item in urls[:40]:
                if isinstance(item, dict) and is_web_url(str(item.get("url", ""))):
                    self.browser.new_tab(str(item["url"]), pinned=bool(item.get("pinned", False)))
        self.browser.save(); self.browser.refresh_bookmark_bar(); self.refresh(name)
        self.browser.statusBar().showMessage(f"Çalışma alanı açıldı: {name}", 2200)
        self.accept()

    def rename(self):
        old = self._selected_name()
        if not old: return
        name, ok = QInputDialog.getText(self, "Adını değiştir", "Yeni ad:", text=old)
        name = name.strip()
        if not ok or not name or name == old: return
        if name in self._workspaces(): QMessageBox.information(self, "Çalışma alanları", "Bu ad zaten kullanılıyor."); return
        workspaces = self._workspaces(); workspaces[name] = workspaces.pop(old)
        settings = self.browser.data.setdefault("settings", {})
        if settings.get("active_workspace") == old: settings["active_workspace"] = name
        self.browser.save(); self.refresh(name)

    def delete(self):
        name = self._selected_name()
        if not name: return
        if QMessageBox.question(self, "Çalışma alanını sil", f"'{name}' alanı silinsin mi?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes: return
        self._workspaces().pop(name, None)
        settings = self.browser.data.setdefault("settings", {})
        if settings.get("active_workspace") == name: settings["active_workspace"] = "Genel"
        self.browser.save(); self.refresh()


class OSSHomePersonalizationDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser
        self.setWindowTitle("OSS Başlangıç Sayfasını Özelleştir"); self.resize(520, 330)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Başlangıç sayfasının görünümünü ve karşılama metnini kişiselleştir."))
        form = QFormLayout(); root.addLayout(form)
        self.style = QComboBox(); self.style.addItem("Aurora — Mor / mavi", "aurora"); self.style.addItem("Midnight — Siyah / mavi", "midnight"); self.style.addItem("Forest — Yeşil", "forest"); self.style.addItem("Light — Açık tema", "light")
        current = browser.data.get("settings", {}).get("home_style", "aurora")
        i = self.style.findData(current); self.style.setCurrentIndex(max(i, 0))
        self.greeting = QLineEdit(browser.data.get("settings", {}).get("home_greeting", "Merak ettiğin konulara göz at"))
        self.clock = QCheckBox("Ana sayfada saat ve tarih göster"); self.clock.setChecked(bool(browser.data.get("settings", {}).get("home_show_clock", True)))
        self.recent = QCheckBox("Son ziyaret edilen sayfaları göster"); self.recent.setChecked(bool(browser.data.get("settings", {}).get("home_show_recent", True)))
        settings = browser.data.get("settings", {})
        self.weather = QCheckBox("Ana sayfada hava durumu göster (internet gerekir)"); self.weather.setChecked(bool(settings.get("home_show_weather", False)))
        self.city = QLineEdit(str(settings.get("home_weather_city", "Ankara"))); self.city.setPlaceholderText("Örn. Ankara")
        form.addRow("Tema", self.style); form.addRow("Karşılama metni", self.greeting); form.addRow("Saat", self.clock); form.addRow("Geçmiş kartı", self.recent); form.addRow("Hava durumu", self.weather); form.addRow("Şehir", self.city)
        root.addWidget(QLabel("Site kartlarını mevcut hızlı bağlantı yöneticisinden düzenleyebilirsin."))
        row = QHBoxLayout(); save = QPushButton("Kaydet"); save.clicked.connect(self.save); row.addWidget(save)
        shortcuts = QPushButton("Hızlı bağlantıları düzenle"); shortcuts.clicked.connect(browser.open_home_shortcuts_manager); row.addWidget(shortcuts)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); row.addWidget(close); root.addLayout(row)

    def save(self):
        settings = self.browser.data.setdefault("settings", {})
        settings["home_style"] = str(self.style.currentData() or "aurora")
        settings["home_greeting"] = self.greeting.text().strip()[:90] or "Merak ettiğin konulara göz at"
        settings["home_show_clock"] = self.clock.isChecked()
        settings["home_show_recent"] = self.recent.isChecked()
        settings["home_show_weather"] = self.weather.isChecked()
        settings["home_weather_city"] = self.city.text().strip()[:64] or "Ankara"
        self.browser.save(); self.browser.refresh_home_pages(); self.browser.statusBar().showMessage("Başlangıç sayfası ayarları kaydedildi.", 2200)


class OSSSiteInfoDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser
        self.setWindowTitle("OSS Site Bilgileri"); self.resize(580, 390)
        root = QVBoxLayout(self); view = browser.current_view()
        url_text = view.url().toString() if view else ""
        parsed = urlparse(url_text)
        try: title = view.title() or "Başlık bulunmuyor"
        except Exception: title = "Başlık bulunmuyor"
        scheme = parsed.scheme.upper() or "Bilinmiyor"
        if scheme == "HTTPS": desc = "Bağlantı HTTPS kullanıyor. Bu, bağlantının şifreli olduğunu gösterir; sitenin içeriğinin güvenilir olduğunu garanti etmez."
        elif scheme == "HTTP": desc = "Bu sayfa HTTPS kullanmıyor; gönderilen veriler şifrelenmeyebilir."
        else: desc = "Bu sayfa normal bir HTTP/HTTPS web adresi değil."
        details = QPlainTextEdit(); details.setReadOnly(True)
        details.setPlainText(f"Başlık: {title}\nAdres: {url_text}\nAlan adı: {parsed.hostname or '—'}\nProtokol: {scheme}\nPort: {parsed.port or ('443' if scheme == 'HTTPS' else '80' if scheme == 'HTTP' else '—')}\n\n{desc}\n\nNot: Bu panel sertifika zincirini ayrıntılı doğrulama raporu olarak sunmaz.")
        root.addWidget(details, 1)
        row = QHBoxLayout()
        copy_btn = QPushButton("Adresi kopyala"); copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(url_text)); row.addWidget(copy_btn)
        perms = QPushButton("Site izinleri"); perms.clicked.connect(browser.open_permissions); row.addWidget(perms)
        clear = QPushButton("Bu sitenin çerezlerini temizle"); clear.clicked.connect(browser.clear_current_site_cookies); row.addWidget(clear)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); row.addWidget(close)
        root.addLayout(row)


class OSSSplitViewDialog(QDialog):
    """İki ayrı sayfayı yatay bölünmüş pencerede görüntüler."""
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser
        self.setWindowTitle("OSS Bölünmüş Ekran"); self.resize(1280, 780)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("İki sayfayı yan yana karşılaştır. Bu penceredeki sekmeler ana sekme listesinden ayrıdır."))
        split = QSplitter(Qt.Orientation.Horizontal); root.addWidget(split, 1)
        profile = browser.current_tab().profile if browser.current_tab() else browser.get_active_profile()
        current_url = browser.current_view().url().toString() if browser.current_view() else ""
        if not is_web_url(current_url) or (urlparse(current_url).hostname or "") == NOVA_SEARCH_HOST:
            current_url = "https://www.wikipedia.org/"
        for idx, initial in enumerate([current_url, "https://www.google.com/"]):
            box = QWidget(); layout = QVBoxLayout(box); layout.setContentsMargins(0,0,0,0)
            bar = QHBoxLayout(); address = QLineEdit(initial); go = QPushButton("Git")
            view = QWebEngineView(); page = QWebEnginePage(profile, view); view.setPage(page)
            def load_url(text=None, view=view, address=address):
                raw = (text if isinstance(text, str) else address.text()).strip()
                engine = self.browser.data.get("settings", {}).get("search_engine", "Google")
                template = SEARCH_ENGINES.get(engine) or GOOGLE_SEARCH
                target = make_url(raw, template) if raw else "https://www.google.com/"
                if target: address.setText(target); view.setUrl(QUrl(target))
            go.clicked.connect(load_url); address.returnPressed.connect(load_url)
            bar.addWidget(address, 1); bar.addWidget(go); layout.addLayout(bar); layout.addWidget(view, 1)
            if initial: view.setUrl(QUrl(initial))
            split.addWidget(box)
        split.setSizes([640, 640])
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); root.addWidget(close)


class OSSQRDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser
        self.setWindowTitle("OSS QR Kod Oluşturucu"); self.resize(520, 250)
        root = QVBoxLayout(self); root.addWidget(QLabel("Bir bağlantı veya metin girip QR kodunu PNG olarak kaydet."))
        self.text = QLineEdit(browser.current_view().url().toString() if browser.current_view() else "https://")
        self.text.setPlaceholderText("URL veya metin")
        root.addWidget(self.text)
        row = QHBoxLayout(); save = QPushButton("QR kodunu PNG kaydet"); save.clicked.connect(self.generate); row.addWidget(save)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); row.addWidget(close); root.addLayout(row)

    def generate(self):
        content = self.text.text().strip()
        if not content: QMessageBox.information(self, "QR Kod", "Önce bir metin veya bağlantı gir."); return
        try:
            import qrcode
            image = qrcode.make(content)
        except ImportError:
            QMessageBox.warning(self, "QR Kod bileşeni eksik", "QR kod için Komut İstemi'nde şu komutu çalıştır:\n\npython -m pip install qrcode[pil]")
            return
        path, _ = QFileDialog.getSaveFileName(self, "QR kodunu kaydet", str(DOWNLOAD_DIR / "oss_qr.png"), "PNG (*.png)")
        if not path: return
        try:
            image.save(path); QMessageBox.information(self, "QR Kod", "Kaydedildi:\n" + path)
        except Exception as exc: QMessageBox.warning(self, "QR Kod", str(exc))


class OSSCommandPaletteDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser
        self.setWindowTitle("OSS Hızlı Komut Merkezi"); self.resize(640, 520)
        root = QVBoxLayout(self); self.search = QLineEdit(); self.search.setPlaceholderText("Özellik ara: not, QR, site bilgisi, NOVA..."); root.addWidget(self.search)
        self.list = QListWidget(); root.addWidget(self.list, 1)
        self.commands = [
            ("Yeni sekme", browser.new_tab), ("Gizli sekme", lambda: browser.new_tab(private=True)),
            ("Kapalı sekmeyi geri aç", browser.reopen_closed_tab), ("Yer imleri", lambda: BookmarkDialog(browser).exec()),
            ("Geçmiş", lambda: HistoryDialog(browser).exec()), ("İndirme yöneticisi", lambda: DownloadsDialog(browser).exec()),
            ("Uzantılar", browser.open_extensions), ("Ayarlar", browser.open_settings),
            ("Çalışma alanları", lambda: OSSWorkspacesDialog(browser).exec()), ("OSS not defteri", lambda: OSSNotesDialog(browser).exec()),
            ("Bölünmüş ekran", lambda: OSSSplitViewDialog(browser).exec()), ("Başlangıç sayfasını özelleştir", lambda: OSSHomePersonalizationDialog(browser).exec()),
            ("Site bilgileri", lambda: OSSSiteInfoDialog(browser).exec()), ("QR kod oluşturucu", lambda: OSSQRDialog(browser).exec()),
            ("NOVA dizin yönetimi", lambda: OSSNovaAdminDialog(browser).exec()), ("Sekme görev yöneticisi", lambda: OSSTaskManagerDialog(browser).exec()),
            ("Gizlilik merkezi", browser.open_privacy_center), ("Güvenlik merkezi", browser.open_security_center),
            ("NOVA arama filtreleri", browser.open_nova_filters), ("Sayfa araçları", browser.open_page_tools),
            ("Yedekleme ve geri yükleme", lambda: _v5_open_backup(browser)), ("Performans merkezi", lambda: V5PerformanceDialog(browser).exec()),
            ("YouTube araçları", lambda: _v5_open_youtube(browser)), ("Güncellemeleri denetle", lambda: _oss_update_begin_check(browser, False)),
        ]
        self.search.textChanged.connect(self.refresh); self.list.itemDoubleClicked.connect(lambda _item: self.run_current()); self.search.returnPressed.connect(self.run_current)
        self.refresh(); self.search.setFocus()

    def refresh(self):
        q = self.search.text().casefold(); self.list.clear()
        for label, _cb in self.commands:
            if not q or q in label.casefold(): self.list.addItem(label)
        if self.list.count(): self.list.setCurrentRow(0)

    def run_current(self):
        item = self.list.currentItem()
        if not item: return
        chosen = item.text()
        callback = next((cb for label, cb in self.commands if label == chosen), None)
        self.accept()
        if callback:
            try: callback()
            except Exception as exc: QMessageBox.warning(self.browser, "OSS Komut Merkezi", str(exc))


class OSSNovaAdminDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser
        self.setWindowTitle("NOVA Search — Dizin Yönetimi"); self.resize(700, 490)
        root = QVBoxLayout(self)
        self.info = QLabel(); self.info.setWordWrap(True); root.addWidget(self.info)
        root.addWidget(QLabel("NOVA kendi yerel indeksindeki sayfaları arar; tüm interneti kapsaması garanti değildir."))
        form = QHBoxLayout(); self.domain = QLineEdit(); self.domain.setPlaceholderText("Ek kaynak alan adı, ör. docs.python.org")
        add = QPushButton("Kaynak ekle"); add.clicked.connect(self.add_source); form.addWidget(self.domain, 1); form.addWidget(add); root.addLayout(form)
        self.sources = QListWidget(); root.addWidget(self.sources, 1)
        row = QHBoxLayout()
        start = QPushButton("Dizini güncelle / taramayı başlat"); start.clicked.connect(self.start_crawl); row.addWidget(start)
        stop = QPushButton("Taramayı durdur"); stop.clicked.connect(self.stop_crawl); row.addWidget(stop)
        remove = QPushButton("Seçili kaynağı kaldır"); remove.clicked.connect(self.remove_source); row.addWidget(remove)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); row.addWidget(close); root.addLayout(row)
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(1500); self.refresh()

    def refresh(self):
        try:
            snap = _nova_status_snapshot(self.browser)
            self.info.setText(f"Dizinlenen sayfa: {snap.get('indexed',0):,} · Bu oturumda taranan: {snap.get('pages',0):,} · Kuyruk: {snap.get('queued',0):,} · Hata: {snap.get('errors',0):,} · Durum: {'Taranıyor' if snap.get('running') else 'Beklemede'}")
        except Exception as exc: self.info.setText("NOVA durumu okunamadı: " + str(exc))
        self.sources.clear()
        seeds = self.browser.data.get("nova_custom_sources", [])
        for item in seeds: self.sources.addItem(str(item))

    def add_source(self):
        raw = self.domain.text().strip()
        if not raw: return
        parsed = urlparse(raw if "://" in raw else "https://" + raw)
        if not parsed.hostname or "." not in parsed.hostname or parsed.scheme not in ("http", "https"):
            QMessageBox.warning(self, "NOVA", "Geçerli bir alan adı gir. Örnek: docs.python.org"); return
        url = parsed._replace(path=parsed.path or "/", params="", query="", fragment="").geturl()
        custom = self.browser.data.setdefault("nova_custom_sources", [])
        domain = parsed.hostname.lower()
        if any((urlparse(x).hostname or "").lower() == domain for x in custom):
            QMessageBox.information(self, "NOVA", "Bu alan adı zaten ekli."); return
        custom.append(url); self.browser.save()
        if url not in NOVA_SEEDS: NOVA_SEEDS.append(url)
        self.domain.clear(); self.refresh(); self.browser.statusBar().showMessage("Kaynak eklendi; bir sonraki taramada kullanılacak.", 2500)

    def remove_source(self):
        item = self.sources.currentItem()
        if not item: return
        url = item.text(); custom = self.browser.data.setdefault("nova_custom_sources", [])
        self.browser.data["nova_custom_sources"] = [x for x in custom if x != url]
        try:
            if url in NOVA_SEEDS: NOVA_SEEDS.remove(url)
        except Exception: pass
        self.browser.save(); self.refresh()

    def start_crawl(self):
        crawler = getattr(self.browser, "_nova_crawler", None)
        if crawler and crawler.running:
            QMessageBox.information(self, "NOVA", "Tarama zaten çalışıyor. Önce durdurup yeniden başlatabilirsin."); return
        _nova_start_crawler(self.browser, force=True); self.refresh()

    def stop_crawl(self):
        crawler = getattr(self.browser, "_nova_crawler", None)
        if crawler and crawler.running:
            crawler.stop_flag = True
            self.browser.statusBar().showMessage("NOVA taraması durdurma isteği aldı.", 2500)
        else: self.browser.statusBar().showMessage("NOVA şu anda tarama yapmıyor.", 2200)


class OSSTaskManagerDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser
        self.setWindowTitle("OSS Sekme Görev Yöneticisi"); self.resize(900, 520)
        root = QVBoxLayout(self); self.summary = QLabel(); root.addWidget(self.summary)
        self.table = QTableWidget(0, 5); self.table.setHorizontalHeaderLabels(["Sekme", "Alan adı", "Durum", "Yükleme (ms)", "İndeks"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, 1)
        row = QHBoxLayout(); refresh = QPushButton("Yenile"); refresh.clicked.connect(self.refresh); row.addWidget(refresh)
        activate = QPushButton("Seçili sekmeye geç"); activate.clicked.connect(self.activate); row.addWidget(activate)
        close = QPushButton("Seçili sekmeyi kapat"); close.clicked.connect(self.close_selected); row.addWidget(close)
        done = QPushButton("Kapat"); done.clicked.connect(self.accept); row.addWidget(done); root.addLayout(row)
        self.refresh()

    def refresh(self):
        try:
            if psutil: self.summary.setText(f"Sistem CPU: {psutil.cpu_percent(interval=None):.0f}% · RAM: {psutil.virtual_memory().percent:.0f}% · Açık sekme: {self.browser.tabs.count()}")
            else: self.summary.setText(f"Açık sekme: {self.browser.tabs.count()} · Sekme başına bellek kullanımı QtWebEngine tarafından bu ekranda ayrı ayrı raporlanmıyor.")
        except Exception: self.summary.setText(f"Açık sekme: {self.browser.tabs.count()}")
        self.table.setRowCount(0)
        for i in range(self.browser.tabs.count()):
            tab = self.browser.tabs.widget(i)
            if not isinstance(tab, BrowserTab): continue
            url = tab.view.url().toString(); title = tab.view.title() or ("Yeni Sekme" if getattr(tab,"is_home",False) else url)
            domain = urlparse(url).hostname or "—"
            status = "Gizli" if tab.private else ("Sabit" if getattr(tab,"pinned",False) else "Açık")
            load_ms = getattr(tab, "_v5_last_load_ms", None)
            values = [title, domain, status, f"{load_ms:.0f}" if load_ms is not None else "—", str(i + 1)]
            row = self.table.rowCount(); self.table.insertRow(row)
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value)); cell.setData(Qt.ItemDataRole.UserRole, i); self.table.setItem(row, col, cell)
        self.table.resizeColumnsToContents()

    def _index(self):
        r = self.table.currentRow()
        if r < 0 or not self.table.item(r, 0): return -1
        return int(self.table.item(r, 0).data(Qt.ItemDataRole.UserRole))

    def activate(self):
        i = self._index()
        if i >= 0: self.browser.tabs.setCurrentIndex(i); self.accept()

    def close_selected(self):
        i = self._index()
        if i >= 0:
            if self.browser.tabs.count() == 1: QMessageBox.information(self, "Görev yöneticisi", "Son sekmeyi kapatamazsın."); return
            self.browser.close_tab(i); self.refresh()


def _oss_v7_open_notes(browser): OSSNotesDialog(browser).exec()
def _oss_v7_open_workspaces(browser): OSSWorkspacesDialog(browser).exec()
def _oss_v7_open_home_customizer(browser): OSSHomePersonalizationDialog(browser).exec()
def _oss_v7_open_site_info(browser): OSSSiteInfoDialog(browser).exec()
def _oss_v7_open_split_view(browser): OSSSplitViewDialog(browser).exec()
def _oss_v7_open_qr(browser): OSSQRDialog(browser).exec()
def _oss_v7_open_command_palette(browser): OSSCommandPaletteDialog(browser).exec()
def _oss_v7_open_nova_admin(browser): OSSNovaAdminDialog(browser).exec()
def _oss_v7_open_task_manager(browser): OSSTaskManagerDialog(browser).exec()

# Make custom NOVA seed sources persistent across launches.
try:
    _oss_crawler_old_run = _NovaCrawler._run
    def _oss_crawler_run_with_user_sources(self):
        global NOVA_SEEDS
        try:
            stored = load_data().get("nova_custom_sources", [])
            for item in stored:
                raw = str(item).strip()
                if raw and raw not in NOVA_SEEDS: NOVA_SEEDS.append(raw)
        except Exception:
            pass
        return _oss_crawler_old_run(self)
    _NovaCrawler._run = _oss_crawler_run_with_user_sources
except Exception:
    pass

# Personalize NOVA's start page without changing its search form behavior.
_oss_nova_home_base_v7 = _nova_home_html
def _oss_nova_home_html_v7(engine_name="NOVA Search", shortcuts=None, browser=None):
    out = _oss_nova_home_base_v7(engine_name, shortcuts, browser)
    try:
        settings = (browser.data.get("settings", {}) if browser else {})
        style = settings.get("home_style", "aurora")
        greeting = html.escape(str(settings.get("home_greeting", "Merak ettiğin konulara göz at"))[:90])
        backgrounds = {
            "aurora": "radial-gradient(ellipse at 10% 0%,#19264b 0,transparent 42%),#080c14",
            "midnight": "radial-gradient(ellipse at 50% -10%,#17233a 0,transparent 50%),#05070c",
            "forest": "radial-gradient(ellipse at 20% 0%,#123c35 0,transparent 45%),#07110f",
            "light": "radial-gradient(ellipse at 15% 0%,#e7ecff 0,transparent 55%),#f4f6fb",
        }
        accent = "#7c5cff" if style != "forest" else "#20b486"
        if style == "light":
            css = "body{background:" + backgrounds[style] + " !important;color:#20283a !important}.panel,.discover-card,.site-card,.search{background:#ffffff !important;color:#20283a !important;border-color:#d8dfeb !important}.discover-heading,.panel-title,.site-card strong{color:#20283a !important}.muted,.discover-desc,.site-card small{color:#5b6678 !important}"
        else:
            css = "body{background:" + backgrounds.get(style, backgrounds["aurora"]) + " !important}.search button{background:linear-gradient(135deg," + accent + ",#42a5ff) !important}.discover-card:hover,.site-card:hover{border-color:" + accent + " !important}"
        css += ".oss-home-clock{font-size:13px;color:#9cacc4;text-align:center;letter-spacing:.5px;margin:8px 0 3px}.oss-home-clock b{font-size:15px;color:inherit;margin-right:7px}"
        out = out.replace("</style>", css + "</style>", 1)
        out = out.replace("Merak ettiğin konulara göz at", greeting)
        extra_css = ".oss-recent{max-width:1080px;margin:18px auto 0;padding:14px 16px;border:1px solid rgba(130,150,190,.22);border-radius:15px;background:rgba(15,23,36,.72)}.oss-recent-head{display:flex;justify-content:space-between;gap:12px;font-size:12px;font-weight:800;margin-bottom:10px;color:#c7d2e7}.oss-recent-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px}.oss-recent a{display:block;min-width:0;padding:10px 12px;border-radius:10px;text-decoration:none;color:#c9d5ff;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06)}.oss-recent a:hover{border-color:#7c5cff}.oss-recent small{display:block;color:#7c8da7;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:4px}.oss-weather{max-width:820px;margin:12px auto 0;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 15px;border-radius:13px;border:1px solid rgba(130,150,190,.22);background:rgba(15,23,36,.72);color:#c9d6eb;font-size:12px}.oss-weather strong{color:#fff}.oss-weather a{color:#b9c5ff;text-decoration:none}.oss-weather span{color:#97a7bf}"
        out = out.replace("</style>", extra_css + "</style>", 1)
        if settings.get("home_show_clock", True):
            clock_html = '<div class="oss-home-clock" id="oss-home-clock"><b></b><span></span></div>'
            marker = '<h2 class="discover-heading">' + greeting + '</h2>'
            if marker in out: out = out.replace(marker, clock_html + marker, 1)
            clock_script = "<script>(function(){function t(){var d=new Date(),el=document.getElementById('oss-home-clock');if(el){el.querySelector('b').textContent=d.toLocaleTimeString('tr-TR',{hour:'2-digit',minute:'2-digit'});el.querySelector('span').textContent=d.toLocaleDateString('tr-TR',{weekday:'long',day:'numeric',month:'long'});}}t();setInterval(t,1000);})();</script>"
            out = out.replace("</body>", clock_script + "</body>", 1)
        if browser and settings.get("home_show_recent", True):
            recent = []
            for item in browser.data.get("history", [])[:5]:
                if not isinstance(item, dict): continue
                rurl = str(item.get("url", "")).strip()
                if not is_web_url(rurl): continue
                rtitle = html.escape(str(item.get("title", "Sayfa"))[:72])
                rdomain = html.escape(urlparse(rurl).hostname or rurl)
                recent.append(f'<a href="{html.escape(rurl, quote=True)}">{rtitle}<small>{rdomain}</small></a>')
            if recent:
                block = '<section class="oss-recent"><div class="oss-recent-head"><span>Son ziyaretler</span><span>Geçmişinden</span></div><div class="oss-recent-list">' + ''.join(recent) + '</div></section>'
                out = out.replace('</main>', block + '</main>', 1)
        if browser and settings.get("home_show_weather", False):
            city = str(settings.get("home_weather_city", "Ankara")).strip()[:64] or "Ankara"
            city_html = html.escape(city)
            city_js = json.dumps(city, ensure_ascii=False).replace("</", "<\\/")
            widget = '<div class="oss-weather" id="oss-weather"><strong>Hava durumu · ' + city_html + '</strong><span>Hava durumu yükleniyor…</span><a href="https://wttr.in/' + quote_plus(city) + '?lang=tr" target="_blank" rel="noopener">Detaylar ↗</a></div>'
            out = out.replace('</form>', '</form>' + widget, 1)
            weather_js = """<script>(async function(){const c=""" + city_js + """;const box=document.getElementById('oss-weather');if(!box)return;const span=box.querySelector('span');try{const g=await fetch('https://geocoding-api.open-meteo.com/v1/search?name='+encodeURIComponent(c)+'&count=1&language=tr&format=json').then(r=>{if(!r.ok)throw Error('network');return r.json()});if(!g.results||!g.results.length)throw Error('city');const p=g.results[0];const u='https://api.open-meteo.com/v1/forecast?latitude='+p.latitude+'&longitude='+p.longitude+'&current=temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code&timezone=auto';const w=await fetch(u).then(r=>{if(!r.ok)throw Error('weather');return r.json()});const x=w.current;const map={0:'Açık',1:'Çoğunlukla açık',2:'Parçalı bulutlu',3:'Kapalı',45:'Sisli',48:'Kırağılı sis',51:'Hafif çisenti',53:'Çisenti',55:'Yoğun çisenti',61:'Hafif yağmur',63:'Yağmur',65:'Kuvvetli yağmur',71:'Hafif kar',73:'Kar',75:'Yoğun kar',80:'Sağanak',81:'Sağanak yağmur',82:'Kuvvetli sağanak',95:'Gök gürültülü fırtına'};span.textContent=Math.round(x.temperature_2m)+'°C · '+(map[x.weather_code]||'Hava durumu')+' · Hissedilen '+Math.round(x.apparent_temperature)+'°C · Nem '+x.relative_humidity_2m+'%';box.querySelector('strong').textContent='Hava durumu · '+(p.name||c);}catch(e){span.textContent='Çevrimiçi hava durumu alınamadı. Bağlantıyı kontrol et.';}})();</script>"""
            out = out.replace('</body>', weather_js + '</body>', 1)
    except Exception:
        pass
    return out
_nova_home_html = _oss_nova_home_html_v7

# Add practical feature entries and shortcuts; leave existing menus/actions intact.
_oss_v7_old_setup_ui = MainWindow.setup_ui
def _oss_v7_setup_ui(self):
    _oss_v7_old_setup_ui(self)
    try:
        menu = self.tools_button.menu() if getattr(self, "tools_button", None) else None
        if menu is not None and not getattr(self, "_oss_v7_menu_ready", False):
            self._oss_v7_menu_ready = True
            menu.addSeparator()
            sub = menu.addMenu("OSS 1.4 — Ek araçlar")
            entries = [
                ("Çalışma Alanları", lambda: _oss_v7_open_workspaces(self)),
                ("OSS Not Defteri", lambda: _oss_v7_open_notes(self)),
                ("Bölünmüş Ekran", lambda: _oss_v7_open_split_view(self)),
                ("Başlangıç Sayfasını Özelleştir", lambda: _oss_v7_open_home_customizer(self)),
                ("Site Bilgileri", lambda: _oss_v7_open_site_info(self)),
                ("QR Kod Oluşturucu", lambda: _oss_v7_open_qr(self)),
                ("Hızlı Komut Merkezi", lambda: _oss_v7_open_command_palette(self)),
                ("NOVA Dizin Yönetimi", lambda: _oss_v7_open_nova_admin(self)),
                ("Sekme Görev Yöneticisi", lambda: _oss_v7_open_task_manager(self)),
                ("Reklam Engelleyici Durumu", lambda: _oss_v7_open_adblock(self)),
            ]
            for label, cb in entries: sub.addAction(label, cb)
        if not getattr(self, "_oss_v7_actions_ready", False):
            self._oss_v7_actions_ready = True
            for label, shortcut, cb in [
                ("OSS Hızlı Komut Merkezi", "Ctrl+K", lambda: _oss_v7_open_command_palette(self)),
                ("OSS Not Defteri", "Ctrl+Shift+N", lambda: _oss_v7_open_notes(self)),
                ("OSS Bölünmüş Ekran", "Ctrl+Shift+D", lambda: _oss_v7_open_split_view(self)),
                ("OSS Çalışma Alanları", "Ctrl+Alt+W", lambda: _oss_v7_open_workspaces(self)),
                ("OSS QR Kod", "Ctrl+Shift+Q", lambda: _oss_v7_open_qr(self)),
                ("OSS Site Bilgileri", "Ctrl+Shift+I", lambda: _oss_v7_open_site_info(self)),
            ]: _oss_v6_add_shortcut(self, label, shortcut, cb)
    except Exception as exc:
        try: self.statusBar().showMessage("OSS araçları eklenirken hata: " + str(exc), 3000)
        except Exception: pass
MainWindow.setup_ui = _oss_v7_setup_ui

# A small, transparent ad-block status panel. Keep existing normal filtering;
# no detection-evasion behavior or guarantee is added here.
def _oss_v7_open_adblock(browser):
    dlg = QDialog(browser); dlg.setWindowTitle("OSS Reklam Engelleyici"); dlg.resize(560, 320)
    root = QVBoxLayout(dlg)
    title = QLabel("Reklam ve izleyici engelleme durumu"); title.setObjectName("SettingsTitle"); root.addWidget(title)
    blocker = getattr(browser, "ad_blocker", AD_BLOCKER)
    check = QCheckBox("Reklam engelleyiciyi etkinleştir"); check.setChecked(bool(getattr(blocker, "enabled", True))); root.addWidget(check)
    info = QLabel(f"Engellenen istek sayısı: {getattr(blocker, 'blocked_count', 0)}\nYouTube reklam alanları ve mevcut filtreler kontrol edilir. YouTube'un kendi tespit/uyarı davranışı zaman içinde değişebilir.")
    info.setWordWrap(True); root.addWidget(info)
    def change(enabled):
        blocker.enabled = bool(enabled)
        browser.data.setdefault("settings", {})["adblock_enabled"] = bool(enabled)
        browser.save()
        for i in range(browser.tabs.count()):
            tab = browser.tabs.widget(i)
            if isinstance(tab, BrowserTab):
                try: tab.view.page().runJavaScript("try{localStorage.setItem('oss_adblock_enabled', %s)}catch(e){}" % ("'1'" if enabled else "'0'"))
                except Exception: pass
        info.setText(f"Durum: {'Etkin' if enabled else 'Kapalı'}\nEngellenen istek sayısı: {getattr(blocker, 'blocked_count', 0)}\nMevcut filtreler değiştirildi; bazı siteler reklam yerleşimlerini değiştirebilir.")
    check.toggled.connect(change)
    close = QPushButton("Kapat"); close.clicked.connect(dlg.accept); root.addWidget(close)
    dlg.exec()

# Honor the saved state of the normal ad-blocking interceptor at startup.
_oss_v7_previous_init = MainWindow.__init__
def _oss_v7_main_init(self, *args, **kwargs):
    _oss_v7_previous_init(self, *args, **kwargs)
    try:
        enabled = bool(self.data.get("settings", {}).get("adblock_enabled", True))
        self.ad_blocker.enabled = enabled
    except Exception:
        pass
MainWindow.__init__ = _oss_v7_main_init



# ============================================================
# OSS BROWSER 2.0 — GELİŞMİŞ ARAÇLAR
# Medya • DPAPI parola kasası • çevrimdışı kütüphane • akıllı sekme arama
# güvenlik/ağ paneli • geçmiş zaman çizelgesi • site karşılaştırma
# web uygulama penceresi • site tercihleri • kısayol düzenleyici
# zamanlanmış yenileme • otomatik yedekleme • performans • eklenti merkezi
# ============================================================

import difflib as _oss_difflib
import ctypes as _oss_ctypes
import ipaddress as _oss_ipaddress

APP_VERSION = "7.0.0"
def _oss_v8_current_url(browser):
    try:
        view = browser.current_view()
        return view.url().toString() if view else ""
    except Exception:
        return ""


def _oss_v8_open_page(browser, url):
    value = str(url or "").strip()
    if not value:
        return
    if not is_web_url(value):
        value = "https://" + value
    try:
        browser.new_tab(value)
    except Exception:
        view = browser.current_view()
        if view:
            view.setUrl(QUrl(value))


# ---- 1. Video mini oynatıcı / Picture-in-Picture ----
def _oss_v8_picture_in_picture(browser):
    view = browser.current_view()
    if not view:
        QMessageBox.information(browser, "Video Mini Oynatıcı", "Önce bir video sayfası aç.")
        return
    js = r"""(()=>{
      try {
        if (document.pictureInPictureElement) { document.exitPictureInPicture().catch(()=>{}); return 'Mini oynatıcı kapatma isteği gönderildi.'; }
        const videos=[...document.querySelectorAll('video')].sort((a,b)=>(b.readyState-a.readyState)||(b.videoWidth*b.videoHeight-a.videoWidth*a.videoHeight));
        const v=videos.find(x=>x.readyState>=2 && !x.disablePictureInPicture) || videos.find(x=>!x.disablePictureInPicture);
        if(!v) return 'Bu sayfada kullanılabilir bir video bulunamadı.';
        v.requestPictureInPicture().catch(e=>{console.warn('OSS PiP:',e);}); return 'Mini oynatıcı isteği gönderildi. Site veya video bu özelliği engelliyor olabilir.';
      } catch(e) { return 'Mini oynatıcı açılamadı: '+(e && e.message ? e.message : String(e)); }
    })()"""
    def done(message):
        try:
            browser.statusBar().showMessage(str(message or "Video mini oynatıcı isteği gönderildi."), 4500)
        except Exception:
            pass
    view.page().runJavaScript(js, done)


# ---- 2. Windows DPAPI ile kullanıcı hesabına bağlı parola kasası ----
def _oss_v8_dpapi(raw: bytes, protect=True) -> bytes:
    if os.name != "nt":
        raise RuntimeError("DPAPI parola kasası yalnızca Windows'ta kullanılabilir.")
    class _DATA_BLOB(_oss_ctypes.Structure):
        _fields_ = [("cbData", _oss_ctypes.wintypes.DWORD),
                    ("pbData", _oss_ctypes.POINTER(_oss_ctypes.c_ubyte))]
    if not hasattr(_oss_ctypes, "wintypes"):
        from ctypes import wintypes as _oss_wintypes
    else:
        _oss_wintypes = _oss_ctypes.wintypes
    # Define the structure with Windows-compatible DWORD fields.
    class DATA_BLOB(_oss_ctypes.Structure):
        _fields_ = [("cbData", _oss_wintypes.DWORD),
                    ("pbData", _oss_ctypes.POINTER(_oss_ctypes.c_ubyte))]
    crypt32 = _oss_ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = _oss_ctypes.WinDLL("kernel32", use_last_error=True)
    in_buffer = _oss_ctypes.create_string_buffer(raw if raw else b"\0")
    in_blob = DATA_BLOB(len(raw), _oss_ctypes.cast(in_buffer, _oss_ctypes.POINTER(_oss_ctypes.c_ubyte)))
    out_blob = DATA_BLOB()
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    if protect:
        fn = crypt32.CryptProtectData
        fn.argtypes = [_oss_ctypes.POINTER(DATA_BLOB), _oss_ctypes.c_wchar_p,
                       _oss_ctypes.POINTER(DATA_BLOB), _oss_ctypes.c_void_p,
                       _oss_ctypes.c_void_p, _oss_wintypes.DWORD,
                       _oss_ctypes.POINTER(DATA_BLOB)]
        fn.restype = _oss_wintypes.BOOL
        ok = fn(_oss_ctypes.byref(in_blob), "OSS Browser Password Vault", None, None, None,
                flags, _oss_ctypes.byref(out_blob))
    else:
        description = _oss_ctypes.c_wchar_p()
        fn = crypt32.CryptUnprotectData
        fn.argtypes = [_oss_ctypes.POINTER(DATA_BLOB), _oss_ctypes.POINTER(_oss_ctypes.c_wchar_p),
                       _oss_ctypes.POINTER(DATA_BLOB), _oss_ctypes.c_void_p,
                       _oss_ctypes.c_void_p, _oss_wintypes.DWORD,
                       _oss_ctypes.POINTER(DATA_BLOB)]
        fn.restype = _oss_wintypes.BOOL
        ok = fn(_oss_ctypes.byref(in_blob), _oss_ctypes.byref(description), None, None, None,
                flags, _oss_ctypes.byref(out_blob))
    if not ok:
        raise OSError(_oss_ctypes.get_last_error(), "Windows DPAPI işlemi başarısız oldu.")
    try:
        result = _oss_ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree.argtypes = [_oss_ctypes.c_void_p]
        kernel32.LocalFree.restype = _oss_ctypes.c_void_p
        kernel32.LocalFree(_oss_ctypes.cast(out_blob.pbData, _oss_ctypes.c_void_p))
        if not protect:
            try:
                if description: kernel32.LocalFree(_oss_ctypes.cast(description, _oss_ctypes.c_void_p))
            except Exception:
                pass
    return result


def _oss_v8_vault_path():
    return APP_DIR / "password_vault.dpapi"


def _oss_v8_vault_load():
    path = _oss_v8_vault_path()
    if not path.exists():
        return []
    raw = _oss_v8_dpapi(path.read_bytes(), protect=False)
    value = json.loads(raw.decode("utf-8"))
    return value if isinstance(value, list) else []


def _oss_v8_vault_save(items):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(items, ensure_ascii=False).encode("utf-8")
    _oss_v8_vault_path().write_bytes(_oss_v8_dpapi(raw, protect=True))


class OSSPasswordVaultDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Güvenli Parola Kasası")
        self.resize(800, 510)
        root = QVBoxLayout(self)
        title = QLabel("Güvenli parola kasası")
        title.setObjectName("SettingsTitle")
        root.addWidget(title)
        note = QLabel("Parolalar Windows DPAPI ile mevcut Windows kullanıcı hesabına bağlı olarak şifrelenir. Bu dosya başka bir Windows hesabında çözülemez. Ana parola yerine Windows hesabı koruması kullanılır.")
        note.setWordWrap(True); root.addWidget(note)
        form = QFormLayout()
        self.name = QLineEdit(); self.name.setPlaceholderText("Örn. GitHub")
        self.user = QLineEdit(); self.user.setPlaceholderText("Kullanıcı adı / e-posta")
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.EchoMode.Password); self.password.setPlaceholderText("Parola")
        self.url = QLineEdit(); self.url.setPlaceholderText("https://... (isteğe bağlı)")
        form.addRow("Kayıt adı", self.name); form.addRow("Kullanıcı adı", self.user)
        form.addRow("Parola", self.password); form.addRow("Site", self.url)
        root.addLayout(form)
        self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(["Kayıt", "Kullanıcı adı", "Site"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, 1)
        row = QHBoxLayout()
        add = QPushButton("Şifreli kaydet"); add.clicked.connect(self.add_item); row.addWidget(add)
        copy_user = QPushButton("Kullanıcı adını kopyala"); copy_user.clicked.connect(lambda: self.copy_field("user")); row.addWidget(copy_user)
        copy_pass = QPushButton("Parolayı kopyala"); copy_pass.clicked.connect(lambda: self.copy_field("password")); row.addWidget(copy_pass)
        delete = QPushButton("Seçili kaydı sil"); delete.clicked.connect(self.delete_item); row.addWidget(delete)
        root.addLayout(row)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); root.addWidget(close)
        self.items = []
        self.refresh()

    def refresh(self):
        try:
            self.items = _oss_v8_vault_load()
        except Exception as exc:
            self.items = []
            if os.name == "nt":
                QMessageBox.warning(self, "Parola kasası", "Kasa okunamadı. Dosya bozulmuş veya farklı bir Windows hesabıyla oluşturulmuş olabilir.\n\n" + str(exc))
            else:
                QMessageBox.information(self, "Parola kasası", "Şifreli parola kasası bu sürümde Windows DPAPI gerektirir.")
        self.table.setRowCount(0)
        for i, item in enumerate(self.items):
            row = self.table.rowCount(); self.table.insertRow(row)
            vals = [item.get("name", "Kayıt"), item.get("user", ""), item.get("url", "")]
            for col, val in enumerate(vals):
                cell = QTableWidgetItem(str(val)); cell.setData(Qt.ItemDataRole.UserRole, i); self.table.setItem(row, col, cell)
        self.table.resizeColumnsToContents()

    def selected_index(self):
        r = self.table.currentRow()
        if r < 0 or self.table.item(r, 0) is None: return -1
        return int(self.table.item(r, 0).data(Qt.ItemDataRole.UserRole))

    def add_item(self):
        name, user, password, url = self.name.text().strip(), self.user.text().strip(), self.password.text(), self.url.text().strip()
        if not name or not password:
            QMessageBox.information(self, "Parola kasası", "Kayıt adı ve parola zorunludur."); return
        if url and not is_web_url(url): url = "https://" + url
        try:
            items = _oss_v8_vault_load()
            items.append({"name": name[:120], "user": user[:300], "password": password, "url": url[:1000], "created": datetime.now().isoformat(timespec="seconds")})
            _oss_v8_vault_save(items); self.name.clear(); self.user.clear(); self.password.clear(); self.url.clear(); self.refresh()
            QMessageBox.information(self, "Parola kasası", "Kayıt şifrelenerek kaydedildi.")
        except Exception as exc:
            QMessageBox.warning(self, "Parola kasası", "Kayıt şifrelenemedi:\n" + str(exc))

    def copy_field(self, field):
        i = self.selected_index()
        if i < 0 or i >= len(self.items): return
        value = str(self.items[i].get(field, ""))
        QApplication.clipboard().setText(value)
        self.browser.statusBar().showMessage("Pano kopyalandı. Güvenlik için kullandıktan sonra panoyu temizle.", 4000)

    def delete_item(self):
        i = self.selected_index()
        if i < 0 or i >= len(self.items): return
        if QMessageBox.question(self, "Kaydı sil", "Seçili parola kaydı kalıcı olarak silinsin mi?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes: return
        self.items.pop(i)
        try: _oss_v8_vault_save(self.items); self.refresh()
        except Exception as exc: QMessageBox.warning(self, "Parola kasası", str(exc))


# ---- 3. Çevrimdışı okuma kütüphanesi: sayfa metni yerel saklanır ----
class OSSOfflineLibraryDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser
        self.setWindowTitle("OSS Çevrimdışı Okuma Kütüphanesi"); self.resize(1000, 650)
        root = QVBoxLayout(self)
        title = QLabel("Çevrimdışı okuma kütüphanesi"); title.setObjectName("SettingsTitle"); root.addWidget(title)
        row = QHBoxLayout(); self.search = QLineEdit(); self.search.setPlaceholderText("Kayıtları ara…"); self.search.textChanged.connect(self.refresh); row.addWidget(self.search, 1)
        save_btn = QPushButton("Açık sayfayı kaydet"); save_btn.clicked.connect(self.save_current_page); row.addWidget(save_btn)
        root.addLayout(row)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget(); self.list.currentRowChanged.connect(self.show_selected); split.addWidget(self.list)
        self.body = QTextBrowser(); self.body.setOpenExternalLinks(False); split.addWidget(self.body); split.setSizes([320, 680]); root.addWidget(split, 1)
        buttons = QHBoxLayout(); delete = QPushButton("Seçili kaydı sil"); delete.clicked.connect(self.delete_selected); buttons.addWidget(delete)
        original = QPushButton("Orijinal siteyi aç"); original.clicked.connect(self.open_original); buttons.addWidget(original)
        export = QPushButton("Metni TXT kaydet"); export.clicked.connect(self.export_text); buttons.addWidget(export)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); buttons.addWidget(close); root.addLayout(buttons)
        self.refresh()

    def entries(self):
        value = self.browser.data.setdefault("offline_library", [])
        if not isinstance(value, list): self.browser.data["offline_library"] = []; value = self.browser.data["offline_library"]
        return value

    def refresh(self, *_):
        query = self.search.text().casefold().strip() if hasattr(self, "search") else ""
        self.list.clear()
        for i, item in enumerate(self.entries()):
            label = f"{item.get('title','Kaydedilen sayfa')}\n{item.get('time','')} · {urlparse(item.get('url','')).hostname or ''}"
            if query and query not in (str(item.get('title','')) + " " + str(item.get('url','')) + " " + str(item.get('text',''))).casefold(): continue
            li = QListWidgetItem(label); li.setData(Qt.ItemDataRole.UserRole, i); self.list.addItem(li)
        if self.list.count(): self.list.setCurrentRow(0)
        else: self.body.setPlainText("Henüz kayıt yok. Açık bir sayfada 'Açık sayfayı kaydet' düğmesine bas.")

    def show_selected(self, _row):
        li = self.list.currentItem()
        if not li: return
        i = int(li.data(Qt.ItemDataRole.UserRole)); entries = self.entries()
        if 0 <= i < len(entries):
            item = entries[i]; self.body.setPlainText(f"{item.get('title','')}\n{item.get('url','')}\nKaydedilme: {item.get('time','')}\n\n{item.get('text','')}")

    def save_current_page(self):
        view = self.browser.current_view()
        if not view or not is_web_url(view.url().toString()):
            QMessageBox.information(self, "Çevrimdışı kütüphane", "Önce kaydedilecek bir web sayfası aç."); return
        js = "({title:document.title||location.hostname,url:location.href,text:(document.body&&document.body.innerText||'').slice(0,250000)})"
        def got(value):
            try:
                if not isinstance(value, dict): raise ValueError("Sayfa içeriği okunamadı.")
                record = {"title": str(value.get("title", "Kaydedilen sayfa"))[:300], "url": str(value.get("url", ""))[:2000], "text": str(value.get("text", ""))[:250000], "time": datetime.now().strftime("%d.%m.%Y %H:%M")}
                items = self.entries()
                items.insert(0, record); self.browser.data["offline_library"] = items[:300]; self.browser.save(); self.refresh()
                self.browser.statusBar().showMessage("Sayfa metni çevrimdışı kütüphaneye kaydedildi.", 3500)
            except Exception as exc: QMessageBox.warning(self, "Kayıt başarısız", str(exc))
        view.page().runJavaScript(js, got)

    def delete_selected(self):
        li = self.list.currentItem()
        if not li: return
        i = int(li.data(Qt.ItemDataRole.UserRole)); items = self.entries()
        if 0 <= i < len(items): items.pop(i); self.browser.save(); self.refresh()

    def open_original(self):
        li = self.list.currentItem()
        if not li: return
        i = int(li.data(Qt.ItemDataRole.UserRole)); items = self.entries()
        if 0 <= i < len(items): _oss_v8_open_page(self.browser, items[i].get("url", ""))

    def export_text(self):
        li = self.list.currentItem()
        if not li: return
        i = int(li.data(Qt.ItemDataRole.UserRole)); items = self.entries()
        if not 0 <= i < len(items): return
        item = items[i]; path, _ = QFileDialog.getSaveFileName(self, "Okuma metnini kaydet", str(APP_DIR / "okuma.txt"), "Metin (*.txt)")
        if path:
            Path(path).write_text(f"{item.get('title','')}\n{item.get('url','')}\n\n{item.get('text','')}", encoding="utf-8")


# ---- 4. Akıllı sekme arama ----
class OSSTabFinderDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser
        self.setWindowTitle("OSS Akıllı Sekme Arama"); self.resize(740, 500)
        root = QVBoxLayout(self); self.search = QLineEdit(); self.search.setPlaceholderText("Sekme adı veya adresi yaz…"); self.search.textChanged.connect(self.refresh); root.addWidget(self.search)
        self.list = QListWidget(); self.list.itemDoubleClicked.connect(lambda *_: self.activate()); root.addWidget(self.list, 1)
        row = QHBoxLayout(); go = QPushButton("Sekmeye geç"); go.clicked.connect(self.activate); row.addWidget(go)
        close = QPushButton("Seçili sekmeyi kapat"); close.clicked.connect(self.close_selected); row.addWidget(close)
        done = QPushButton("Kapat"); done.clicked.connect(self.accept); row.addWidget(done); root.addLayout(row)
        self.refresh(); self.search.setFocus()

    def refresh(self, *_):
        query = self.search.text().casefold().strip(); self.list.clear()
        for i in range(self.browser.tabs.count()):
            tab = self.browser.tabs.widget(i)
            if not isinstance(tab, BrowserTab): continue
            title = tab.view.title() or "Yeni Sekme"; url = tab.view.url().toString()
            if query and query not in (title + " " + url).casefold(): continue
            item = QListWidgetItem(f"{title}\n{url or 'Yeni sekme'}"); item.setData(Qt.ItemDataRole.UserRole, i); self.list.addItem(item)

    def activate(self):
        item = self.list.currentItem()
        if item: self.browser.tabs.setCurrentIndex(int(item.data(Qt.ItemDataRole.UserRole))); self.accept()

    def close_selected(self):
        item = self.list.currentItem()
        if item:
            idx = int(item.data(Qt.ItemDataRole.UserRole))
            if self.browser.tabs.count() > 1: self.browser.close_tab(idx); self.refresh()


# ---- 5. Gelişmiş site güvenliği / URL kontrolü ----
class OSSSecurityCenterDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser
        self.setWindowTitle("OSS Güvenlik ve Bağlantı Merkezi"); self.resize(720, 480)
        root = QVBoxLayout(self); title = QLabel("Site güvenliği ve bağlantı bilgileri"); title.setObjectName("SettingsTitle"); root.addWidget(title)
        self.report = QTextBrowser(); self.report.setOpenExternalLinks(False); root.addWidget(self.report, 1)
        row = QHBoxLayout(); refresh = QPushButton("Geçerli siteyi denetle"); refresh.clicked.connect(self.refresh); row.addWidget(refresh)
        permissions = QPushButton("Site izinleri"); permissions.clicked.connect(lambda: browser.open_permissions()); row.addWidget(permissions)
        settings = QPushButton("Gizlilik ayarları"); settings.clicked.connect(lambda: browser.open_settings()); row.addWidget(settings)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); row.addWidget(close); root.addLayout(row)
        self.refresh()

    def refresh(self):
        url = _oss_v8_current_url(self.browser); parsed = urlparse(url); host = parsed.hostname or ""
        issues = []
        if parsed.scheme == "https": status = "HTTPS adresi kullanılıyor"
        elif parsed.scheme == "http": status = "HTTP — trafik şifreli değil"; issues.append("Bu bağlantıda HTTPS şifrelemesi görünmüyor.")
        elif not url: status = "Açık URL yok"
        else: status = "Web dışı adres şeması: " + parsed.scheme
        try: _oss_ipaddress.ip_address(host); issues.append("Adres bir IP numarası kullanıyor; bu tek başına kötü niyet göstergesi değildir.")
        except Exception: pass
        if "xn--" in host.lower(): issues.append("Alan adı Punycode içeriyor; uluslararası karakterleri dikkatle kontrol et.")
        if parsed.username or parsed.password: issues.append("URL içinde kullanıcı bilgisi var; bu URL biçimi riskli olabilir.")
        if len(host) > 50: issues.append("Alan adı alışılmadık derecede uzun.")
        if host.count("-") >= 4: issues.append("Alan adında çok sayıda tire var; alan adını elle doğrula.")
        body = [f"Adres: {url or '—'}", f"Alan adı: {host or '—'}", f"Durum: {status}", "", "Kontrol notları:"]
        body += ["• " + x for x in issues] if issues else ["• Basit URL kontrollerinde belirgin bir uyarı bulunmadı."]
        body += ["", "Bu panel temel adres kontrolleri yapar; gerçek bir itibar servisi veya antivirüs değildir. HTTPS tek başına sitenin güvenilir olduğunu kanıtlamaz."]
        self.report.setPlainText("\n".join(body))


# ---- 6. Ağ tanılama ----
class OSSNetworkProbeThread(QThread):
    result_line = Signal(str)
    def run(self):
        targets = [("Cloudflare", "https://www.cloudflare.com/"), ("Google", "https://www.google.com/"), ("GitHub", "https://github.com/"), ("NOVA/site", "https://example.com/")]
        for name, url in targets:
            start = time.monotonic()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "OSS-Browser-NetworkCheck/2.0"}, method="HEAD")
                try:
                    with urllib.request.urlopen(req, timeout=6) as response: code = getattr(response, "status", 200)
                except Exception:
                    req = urllib.request.Request(url, headers={"User-Agent": "OSS-Browser-NetworkCheck/2.0", "Range": "bytes=0-0"})
                    with urllib.request.urlopen(req, timeout=6) as response: code = getattr(response, "status", 200); response.read(64)
                ms = (time.monotonic() - start) * 1000
                self.result_line.emit(f"✓ {name}: erişilebilir · HTTP {code} · {ms:.0f} ms")
            except Exception as exc:
                ms = (time.monotonic() - start) * 1000
                self.result_line.emit(f"✗ {name}: başarısız · {ms:.0f} ms · {str(exc)[:160]}")


class OSSNetworkDiagnosticsDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.setWindowTitle("OSS Ağ Tanılama"); self.resize(700, 430)
        root = QVBoxLayout(self); title = QLabel("Ağ bağlantısı testi"); title.setObjectName("SettingsTitle"); root.addWidget(title)
        root.addWidget(QLabel("Bu test birkaç HTTPS adresine bağlantıyı ölçer; internet hız testi veya DNS güvenlik denetimi değildir."))
        self.output = QPlainTextEdit(); self.output.setReadOnly(True); root.addWidget(self.output, 1)
        row = QHBoxLayout(); run = QPushButton("Testi başlat"); run.clicked.connect(self.start); row.addWidget(run)
        copy = QPushButton("Sonuçları kopyala"); copy.clicked.connect(lambda: QApplication.clipboard().setText(self.output.toPlainText())); row.addWidget(copy)
        done = QPushButton("Kapat"); done.clicked.connect(self.accept); row.addWidget(done); root.addLayout(row)
        self.worker = None; self.start()

    def start(self):
        if self.worker and self.worker.isRunning(): return
        self.output.clear(); self.output.appendPlainText("HTTPS erişim testi başlıyor…\n")
        self.worker = OSSNetworkProbeThread(browser); self.worker.result_line.connect(self.output.appendPlainText); self.worker.finished.connect(lambda: self.output.appendPlainText("\nTest tamamlandı.")); self.worker.start()


# ---- 7. Geçmiş zaman çizelgesi ----
class OSSTimelineDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser
        self.setWindowTitle("OSS Geçmiş Zaman Çizelgesi"); self.resize(860, 560)
        root = QVBoxLayout(self); self.search = QLineEdit(); self.search.setPlaceholderText("Başlık, alan adı veya tarih ara…"); self.search.textChanged.connect(self.refresh); root.addWidget(self.search)
        self.list = QListWidget(); self.list.itemDoubleClicked.connect(lambda *_: self.open_selected()); root.addWidget(self.list, 1)
        row = QHBoxLayout(); openb = QPushButton("Seçili sayfayı aç"); openb.clicked.connect(self.open_selected); row.addWidget(openb)
        export = QPushButton("Geçmişi CSV dışa aktar"); export.clicked.connect(self.export_csv); row.addWidget(export)
        clear = QPushButton("Filtrelenen kayıtları temizle"); clear.clicked.connect(self.clear_filtered); row.addWidget(clear)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); row.addWidget(close); root.addLayout(row); self.refresh()

    def refresh(self, *_):
        q = self.search.text().casefold().strip(); self.list.clear()
        for idx, item in enumerate(self.browser.data.get("history", [])):
            if not isinstance(item, dict): continue
            title = str(item.get("title", "Sayfa")); url = str(item.get("url", "")); when = str(item.get("time", ""))
            if q and q not in (title + " " + url + " " + when).casefold(): continue
            li = QListWidgetItem(f"{when}  ·  {title}\n{url}"); li.setData(Qt.ItemDataRole.UserRole, idx); self.list.addItem(li)

    def open_selected(self):
        li = self.list.currentItem()
        if li:
            i = int(li.data(Qt.ItemDataRole.UserRole)); hist = self.browser.data.get("history", [])
            if 0 <= i < len(hist): _oss_v8_open_page(self.browser, hist[i].get("url", ""))

    def export_csv(self):
        import csv as _oss_csv
        path, _ = QFileDialog.getSaveFileName(self, "Geçmişi kaydet", str(APP_DIR / "gecmis.csv"), "CSV (*.csv)")
        if not path: return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = _oss_csv.writer(f); w.writerow(["Zaman", "Başlık", "Adres"])
            for item in self.browser.data.get("history", []):
                if isinstance(item, dict): w.writerow([item.get("time", ""), item.get("title", ""), item.get("url", "")])

    def clear_filtered(self):
        q = self.search.text().casefold().strip()
        if not q:
            QMessageBox.warning(self, "Geçmiş", "Tüm geçmişi burada temizlemek yerine geçmiş yönetimini kullan. Önce bir arama filtresi gir."); return
        old = self.browser.data.get("history", []); self.browser.data["history"] = [x for x in old if q not in (str(x.get("title", "")) + " " + str(x.get("url", "")) + " " + str(x.get("time", ""))).casefold()]
        self.browser.save(); self.refresh()


# ---- 8. İki web sitesini yan yana karşılaştırma ----
class OSSCompareSitesDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser; self.setWindowTitle("OSS Site Karşılaştırma"); self.resize(1200, 760)
        root = QVBoxLayout(self); row = QHBoxLayout()
        current = _oss_v8_current_url(browser) or "https://example.com/"
        self.url1 = QLineEdit(current); self.url1.setPlaceholderText("Birinci adres"); row.addWidget(self.url1)
        self.url2 = QLineEdit("https://example.org/"); self.url2.setPlaceholderText("İkinci adres"); row.addWidget(self.url2)
        load = QPushButton("İki siteyi aç"); load.clicked.connect(self.load_sites); row.addWidget(load); root.addLayout(row)
        split = QSplitter(Qt.Orientation.Horizontal); self.view1 = QWebEngineView(self); self.view2 = QWebEngineView(self)
        try: self.view1.setPage(BrowserPage(browser, browser.get_active_profile(), self)); self.view2.setPage(BrowserPage(browser, browser.get_active_profile(), self))
        except Exception: pass
        split.addWidget(self.view1); split.addWidget(self.view2); root.addWidget(split, 3)
        row2 = QHBoxLayout(); compare = QPushButton("Metin farklılıklarını bul"); compare.clicked.connect(self.compare_text); row2.addWidget(compare)
        self.status = QLabel("Siteler yüklenip karşılaştırılabilir."); row2.addWidget(self.status, 1)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); row2.addWidget(close); root.addLayout(row2)
        self.diff = QTextBrowser(); self.diff.setMinimumHeight(170); root.addWidget(self.diff, 2)
        self.load_sites()

    @staticmethod
    def _normal_url(value):
        value = value.strip()
        if value and not urlparse(value).scheme: value = "https://" + value
        return value

    def load_sites(self):
        a, b = self._normal_url(self.url1.text()), self._normal_url(self.url2.text())
        if not is_web_url(a) or not is_web_url(b):
            QMessageBox.warning(self, "Karşılaştırma", "İki geçerli HTTP/HTTPS adresi gir."); return
        self.view1.setUrl(QUrl(a)); self.view2.setUrl(QUrl(b)); self.status.setText("Sayfalar yükleniyor…")

    def compare_text(self):
        self.status.setText("Sayfa metinleri alınıyor…")
        result = {"left": None, "right": None}
        def got(key, value):
            result[key] = str(value or "")
            if result["left"] is not None and result["right"] is not None:
                left = result["left"].splitlines(); right = result["right"].splitlines()
                diff = _oss_difflib.HtmlDiff(wrapcolumn=100).make_file(left, right, "Site A", "Site B", context=True, numlines=3)
                self.diff.setHtml(diff); self.status.setText(f"Karşılaştırma tamamlandı · A: {len(left)} satır · B: {len(right)} satır")
        self.view1.page().runJavaScript("(document.body&&document.body.innerText)||''", lambda value: got("left", value))
        self.view2.page().runJavaScript("(document.body&&document.body.innerText)||''", lambda value: got("right", value))


# ---- 9. Kromsuz web uygulama penceresi ----
def _oss_v8_open_web_app(browser):
    url = _oss_v8_current_url(browser)
    if not is_web_url(url):
        url, ok = QInputDialog.getText(browser, "Web Uygulaması", "Açılacak sitenin adresi:", text="https://")
        if not ok or not url.strip(): return
    if not urlparse(url).scheme: url = "https://" + url
    dlg = QDialog(None, Qt.WindowType.Window)
    dlg.setWindowTitle("OSS Web Uygulaması — " + (urlparse(url).hostname or "Site")); dlg.resize(1100, 760)
    root = QVBoxLayout(dlg); root.setContentsMargins(4, 4, 4, 4)
    bar = QHBoxLayout(); address = QLineEdit(url); bar.addWidget(address, 1)
    go = QPushButton("Git"); bar.addWidget(go); root.addLayout(bar)
    view = QWebEngineView(dlg)
    try: view.setPage(BrowserPage(browser, browser.get_active_profile(), dlg))
    except Exception: pass
    root.addWidget(view, 1)
    go.clicked.connect(lambda: view.setUrl(QUrl(address.text().strip() if urlparse(address.text()).scheme else "https://" + address.text().strip())))
    address.returnPressed.connect(go.click); view.urlChanged.connect(lambda q: address.setText(q.toString()))
    view.setUrl(QUrl(url));
    if not hasattr(browser, "_oss_v8_app_windows"): browser._oss_v8_app_windows = []
    browser._oss_v8_app_windows.append(dlg)
    dlg.finished.connect(lambda *_: browser._oss_v8_app_windows.remove(dlg) if dlg in browser._oss_v8_app_windows else None)
    dlg.show()


# ---- 10. Siteye özel görünüm / izin tercihleri ----
class OSSSitePreferencesDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser; self.setWindowTitle("OSS Siteye Özel Ayarlar"); self.resize(590, 420)
        root = QVBoxLayout(self); title = QLabel("Siteye özel ayarlar"); title.setObjectName("SettingsTitle"); root.addWidget(title)
        self.url_label = QLabel(); root.addWidget(self.url_label)
        form = QFormLayout(); self.zoom = QSpinBox(); self.zoom.setRange(50, 200); self.zoom.setSuffix("%"); form.addRow("Yakınlaştırma", self.zoom)
        self.js = QCheckBox("JavaScript'e izin ver"); form.addRow("Sayfa işlevleri", self.js)
        self.dark = QCheckBox("Bu site için koyu görünüm CSS'i uygula"); form.addRow("Görünüm", self.dark)
        self.mute = QCheckBox("Bu sitenin sesini kapat"); form.addRow("Ses", self.mute); root.addLayout(form)
        note = QLabel("Ayarlar alan adına kaydedilir ve sonraki yüklemede uygulanır. Bazı siteler JavaScript olmadan çalışmayabilir. Koyu görünüm her sayfada kusursuz sonuç vermeyebilir."); note.setWordWrap(True); root.addWidget(note)
        row = QHBoxLayout(); save = QPushButton("Kaydet ve uygula"); save.clicked.connect(self.save_preferences); row.addWidget(save)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); row.addWidget(close); root.addLayout(row)
        self.host = urlparse(_oss_v8_current_url(browser)).hostname or ""
        if not self.host: self.host = "example.com"
        self.url_label.setText("Alan adı: " + self.host)
        pref = browser.data.setdefault("site_preferences", {}).get(self.host, {})
        self.zoom.setValue(int(pref.get("zoom", round(float(browser.current_view().zoomFactor() if browser.current_view() else 1)*100))))
        self.js.setChecked(bool(pref.get("javascript", True))); self.dark.setChecked(bool(pref.get("dark", False))); self.mute.setChecked(bool(pref.get("muted", False)))

    def save_preferences(self):
        value = {"zoom": self.zoom.value(), "javascript": self.js.isChecked(), "dark": self.dark.isChecked(), "muted": self.mute.isChecked()}
        self.browser.data.setdefault("site_preferences", {})[self.host] = value; self.browser.save()
        _oss_v8_apply_site_preferences(self.browser, self.browser.current_tab())
        self.browser.statusBar().showMessage("Siteye özel ayarlar kaydedildi.", 3000); self.accept()


def _oss_v8_apply_site_preferences(browser, tab):
    try:
        if not isinstance(tab, BrowserTab): return
        host = (urlparse(tab.view.url().toString()).hostname or "").lower()
        prefs = browser.data.get("site_preferences", {}).get(host, {})
        if not prefs: return
        tab.view.setZoomFactor(max(0.5, min(2.0, float(prefs.get("zoom", 100)) / 100.0)))
        tab.view.page().settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, bool(prefs.get("javascript", True)))
        try: tab.view.page().setAudioMuted(bool(prefs.get("muted", False)))
        except Exception: pass
        if prefs.get("dark") and prefs.get("javascript", True):
            tab.view.page().runJavaScript("(()=>{if(!document.getElementById('__oss_site_dark__')){const s=document.createElement('style');s.id='__oss_site_dark__';s.textContent='html{filter:invert(.90) hue-rotate(180deg)!important;background:#111!important}img,video,canvas,svg,iframe{filter:invert(1) hue-rotate(180deg)!important}';document.documentElement.appendChild(s)}})()")
        else:
            tab.view.page().runJavaScript("document.getElementById('__oss_site_dark__')?.remove()")
    except Exception:
        pass


# ---- 11. Var olan kısayolları değiştirme ----
class OSSShortcutEditorDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser; self.setWindowTitle("OSS Kısayol Düzenleyici"); self.resize(760, 520)
        root = QVBoxLayout(self); root.addWidget(QLabel("Kısayolu değiştirmek için satırdaki alana tıkla ve yeni tuş kombinasyonuna bas."))
        self.table = QTableWidget(0, 2); self.table.setHorizontalHeaderLabels(["Komut", "Klavye kısayolu"]); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); root.addWidget(self.table, 1)
        self.rows = []
        for action in getattr(browser, "_oss_v6_shortcuts", []):
            if not isinstance(action, QAction): continue
            r = self.table.rowCount(); self.table.insertRow(r); self.table.setItem(r, 0, QTableWidgetItem(action.text()))
            editor = QKeySequenceEdit(action.shortcut(), self.table); self.table.setCellWidget(r, 1, editor); self.rows.append((action, editor))
        row = QHBoxLayout(); save = QPushButton("Kısayolları kaydet"); save.clicked.connect(self.save); row.addWidget(save)
        reset = QPushButton("Varsayılanlara dön"); reset.clicked.connect(self.reset); row.addWidget(reset)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); row.addWidget(close); root.addLayout(row)

    def save(self):
        values = {}; seen = {}
        for action, editor in self.rows:
            seq = editor.keySequence().toString()
            if seq and seq in seen:
                QMessageBox.warning(self, "Kısayol çakışması", f"'{seq}' hem '{seen[seq]}' hem '{action.text()}' için seçilmiş. Çakışmaları düzelt."); return
            if seq: seen[seq] = action.text()
            action.setShortcut(QKeySequence(seq)); values[action.text()] = seq
        self.browser.data.setdefault("settings", {})["custom_shortcuts"] = values; self.browser.save()
        QMessageBox.information(self, "Kısayollar", "Kısayollar kaydedildi.")

    def reset(self):
        defaults = getattr(self.browser, "_oss_v8_default_shortcuts", {})
        for action, editor in self.rows:
            seq = defaults.get(action.text(), "")
            editor.setKeySequence(QKeySequence(seq))


# ---- 12. Zamanlanmış sayfa yenileme ----
class OSSScheduledTasksDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser; self.setWindowTitle("OSS Zamanlanmış Sayfa İşleri"); self.resize(820, 500)
        root = QVBoxLayout(self); form = QFormLayout()
        self.url = QLineEdit(_oss_v8_current_url(browser)); self.url.setPlaceholderText("https://...")
        self.minutes = QSpinBox(); self.minutes.setRange(1, 1440); self.minutes.setValue(30); self.minutes.setSuffix(" dakika")
        form.addRow("Yenilenecek sayfa", self.url); form.addRow("Aralık", self.minutes); root.addLayout(form)
        self.list = QListWidget(); root.addWidget(self.list, 1)
        row = QHBoxLayout(); add = QPushButton("Görevi ekle"); add.clicked.connect(self.add_task); row.addWidget(add)
        toggle = QPushButton("Etkinleştir / duraklat"); toggle.clicked.connect(self.toggle_task); row.addWidget(toggle)
        delete = QPushButton("Görevi sil"); delete.clicked.connect(self.delete_task); row.addWidget(delete)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); row.addWidget(close); root.addLayout(row); self.refresh()

    def tasks(self):
        val = self.browser.data.setdefault("scheduled_tasks", [])
        if not isinstance(val, list): self.browser.data["scheduled_tasks"] = []; val = self.browser.data["scheduled_tasks"]
        return val

    def refresh(self):
        self.list.clear()
        for i, task in enumerate(self.tasks()):
            state = "Etkin" if task.get("enabled", True) else "Duraklatıldı"
            self.list.addItem(QListWidgetItem(f"{'●' if task.get('enabled', True) else '○'} {state} · {task.get('interval_minutes',30)} dk · {task.get('url','')}"))

    def add_task(self):
        url = self.url.text().strip()
        if url and not urlparse(url).scheme: url = "https://" + url
        if not is_web_url(url): QMessageBox.warning(self, "Zamanlanmış işler", "Geçerli bir HTTP/HTTPS adresi gir."); return
        tasks = self.tasks(); tasks.append({"url": url, "interval_minutes": self.minutes.value(), "enabled": True, "next_run": time.time() + self.minutes.value()*60})
        self.browser.save(); self.refresh(); _oss_v8_start_schedule_timer(self.browser)

    def _selected(self):
        i = self.list.currentRow(); return i if 0 <= i < len(self.tasks()) else -1

    def toggle_task(self):
        i = self._selected()
        if i < 0: return
        self.tasks()[i]["enabled"] = not self.tasks()[i].get("enabled", True)
        self.tasks()[i]["next_run"] = time.time() + int(self.tasks()[i].get("interval_minutes", 30))*60
        self.browser.save(); self.refresh()

    def delete_task(self):
        i = self._selected()
        if i >= 0: self.tasks().pop(i); self.browser.save(); self.refresh()


def _oss_v8_check_scheduled_tasks(browser):
    now = time.time()
    tasks = browser.data.get("scheduled_tasks", [])
    changed = False
    for task in tasks:
        if not isinstance(task, dict) or not task.get("enabled", True): continue
        interval = max(1, int(task.get("interval_minutes", 30))) * 60
        if float(task.get("next_run", 0) or 0) > now: continue
        target = str(task.get("url", "")); matched = False
        for i in range(browser.tabs.count()):
            tab = browser.tabs.widget(i)
            if isinstance(tab, BrowserTab) and tab.view.url().toString().split("#", 1)[0] == target.split("#", 1)[0]:
                tab.view.reload(); matched = True
        task["next_run"] = now + interval; changed = True
        try: browser.statusBar().showMessage(("Zamanlanmış sayfa yenilendi: " if matched else "Zamanlanmış görev çalıştı; sayfa açık olmadığı için yenilenmedi: ") + (urlparse(target).hostname or target), 4000)
        except Exception: pass
    if changed: browser.save()


def _oss_v8_start_schedule_timer(browser):
    if not hasattr(browser, "_oss_v8_schedule_timer"):
        browser._oss_v8_schedule_timer = QTimer(browser)
        browser._oss_v8_schedule_timer.setInterval(30000)
        browser._oss_v8_schedule_timer.timeout.connect(lambda: _oss_v8_check_scheduled_tasks(browser))
    browser._oss_v8_schedule_timer.start()


# ---- 13. Performans raporu ----
class OSSPerformanceDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser; self.setWindowTitle("OSS Performans Raporu"); self.resize(650, 470)
        root = QVBoxLayout(self); title = QLabel("Tarayıcı performansı"); title.setObjectName("SettingsTitle"); root.addWidget(title)
        self.report = QTextBrowser(); root.addWidget(self.report, 1)
        row = QHBoxLayout(); refresh = QPushButton("Raporu yenile"); refresh.clicked.connect(self.refresh); row.addWidget(refresh)
        done = QPushButton("Kapat"); done.clicked.connect(self.accept); row.addWidget(done); root.addLayout(row); self.refresh()

    def refresh(self):
        lines = [f"OSS Browser: {APP_VERSION}", f"Açık sekme: {self.browser.tabs.count()}", f"Geçmiş kaydı: {len(self.browser.data.get('history', []))}", f"Yer imi: {len(self.browser.data.get('bookmarks', []))}", f"İndirme nesnesi: {len(getattr(self.browser, 'download_widgets', []))}"]
        try:
            if psutil:
                process = psutil.Process(os.getpid()); mem = process.memory_info().rss / 1024 / 1024
                lines += [f"OSS işlem RAM kullanımı: {mem:.1f} MiB", f"OSS işlem CPU: {process.cpu_percent(interval=None):.1f}%", f"Sistem RAM kullanımı: {psutil.virtual_memory().percent:.1f}%", f"Sistem CPU kullanımı: {psutil.cpu_percent(interval=None):.1f}%"]
            else: lines.append("psutil kurulu değil; CPU/RAM süreç ölçümleri kullanılamıyor.")
        except Exception as exc: lines.append("Sistem ölçümü okunamadı: " + str(exc))
        lines.append("\nNot: Qt WebEngine bu panelde her sekmenin ayrı RAM kullanımını güvenilir şekilde raporlamaz.")
        self.report.setPlainText("\n".join(lines))


# ---- 14. Otomatik yedekleme ----
class OSSAutoBackupDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser; self.setWindowTitle("OSS Otomatik Yedekleme"); self.resize(610, 390)
        root = QVBoxLayout(self); title = QLabel("Otomatik yedekleme ve kurtarma"); title.setObjectName("SettingsTitle"); root.addWidget(title)
        settings = browser.data.setdefault("settings", {})
        self.enabled = QCheckBox("Tarayıcı verilerini otomatik yedekle"); self.enabled.setChecked(bool(settings.get("auto_backup_enabled", False))); root.addWidget(self.enabled)
        form = QFormLayout(); self.interval = QSpinBox(); self.interval.setRange(15, 1440); self.interval.setSuffix(" dakika"); self.interval.setValue(int(settings.get("auto_backup_minutes", 60))); form.addRow("Yedek aralığı", self.interval)
        self.keep = QSpinBox(); self.keep.setRange(1, 50); self.keep.setSuffix(" dosya"); self.keep.setValue(int(settings.get("auto_backup_keep", 10))); form.addRow("Saklanacak yedek", self.keep); root.addLayout(form)
        root.addWidget(QLabel("Yedekler OSSBrowser/AutoBackups klasöründe tutulur. Parola kasası bu dosyaya dahil edilmez. Hassas verileri yedeklemeden önce klasör izinlerini kontrol et."))
        row = QHBoxLayout(); save = QPushButton("Ayarları kaydet"); save.clicked.connect(self.save_settings); row.addWidget(save)
        now = QPushButton("Şimdi yedekle"); now.clicked.connect(lambda: _oss_v8_make_backup(browser)); row.addWidget(now)
        open_folder = QPushButton("Yedek klasörünü aç"); open_folder.clicked.connect(self.open_folder); row.addWidget(open_folder)
        done = QPushButton("Kapat"); done.clicked.connect(self.accept); row.addWidget(done); root.addLayout(row)

    def save_settings(self):
        s = self.browser.data.setdefault("settings", {}); s["auto_backup_enabled"] = self.enabled.isChecked(); s["auto_backup_minutes"] = self.interval.value(); s["auto_backup_keep"] = self.keep.value(); self.browser.save(); _oss_v8_start_backup_timer(self.browser)
        QMessageBox.information(self, "Yedekleme", "Otomatik yedekleme ayarları kaydedildi.")

    def open_folder(self):
        folder = APP_DIR / "AutoBackups"; folder.mkdir(parents=True, exist_ok=True); QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def _oss_v8_make_backup(browser):
    try:
        browser.save(); source = DATA_FILE
        if not source.exists(): raise FileNotFoundError("Tarayıcı veri dosyası bulunamadı.")
        folder = APP_DIR / "AutoBackups"; folder.mkdir(parents=True, exist_ok=True)
        target = folder / ("OSSBackup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json")
        shutil.copy2(source, target)
        keep = max(1, int(browser.data.get("settings", {}).get("auto_backup_keep", 10)))
        items = sorted(folder.glob("OSSBackup_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in items[keep:]:
            try: old.unlink()
            except Exception: pass
        browser.statusBar().showMessage("Yedek oluşturuldu: " + target.name, 4000)
        return str(target)
    except Exception as exc:
        QMessageBox.warning(browser, "Otomatik yedekleme", "Yedekleme başarısız:\n" + str(exc)); return ""


def _oss_v8_start_backup_timer(browser):
    s = browser.data.setdefault("settings", {})
    if not hasattr(browser, "_oss_v8_backup_timer"):
        browser._oss_v8_backup_timer = QTimer(browser)
        browser._oss_v8_backup_timer.timeout.connect(lambda: _oss_v8_make_backup(browser))
    if s.get("auto_backup_enabled", False):
        minutes = max(15, int(s.get("auto_backup_minutes", 60)))
        browser._oss_v8_backup_timer.start(minutes * 60 * 1000)
    else:
        browser._oss_v8_backup_timer.stop()


# ---- 15. Eklenti merkezi ----
class OSSExtensionCenterDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser; self.setWindowTitle("OSS Eklenti Merkezi"); self.resize(650, 430)
        root = QVBoxLayout(self); title = QLabel("Eklenti ve tarayıcı araçları merkezi"); title.setObjectName("SettingsTitle"); root.addWidget(title)
        info = QLabel("OSS Browser, Qt WebEngine eklenti desteği mevcut olduğunda desteklenen uzantıları yönetebilir. Chrome uzantılarının tümü uyumlu olmayabilir. Yalnızca güvendiğin kaynaklardan uzantı yükle.")
        info.setWordWrap(True); root.addWidget(info)
        self.list = QListWidget()
        for name, desc in [("Dahili: Okuma modu", "Web sayfasının metnini sade görünümde kaydetme."), ("Dahili: QR kod", "Açık URL için QR kod üretme."), ("Dahili: Gizlilik merkezi", "Site izinleri ve reklam engelleme durumu."), ("Dahili: NOVA Search", "Yerel web dizini ve arama filtreleri."), ("Web uzantıları", "Qt WebEngine destekliyorsa uyumlu uzantıları yönetme.")]:
            item = QListWidgetItem(name + "\n" + desc); self.list.addItem(item)
        root.addWidget(self.list, 1)
        row = QHBoxLayout(); manage = QPushButton("Uzantıları yönet"); manage.clicked.connect(self.open_extensions); row.addWidget(manage)
        store = QPushButton("Chrome Web Store'u aç"); store.clicked.connect(lambda: browser.open_chrome_store()); row.addWidget(store)
        done = QPushButton("Kapat"); done.clicked.connect(self.accept); row.addWidget(done); root.addLayout(row)

    def open_extensions(self):
        self.browser.open_extensions()



# ---- Extraa. Sekme uyku modu (Qt destekliyorsa Frozen lifecycle) ----
class OSSTabSleepDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser; self.setWindowTitle("OSS Sekme Uyku Modu"); self.resize(800, 500)
        root = QVBoxLayout(self); root.addWidget(QLabel("Arka plandaki sekmeleri uyutmayı deneyebilirsin. Qt sürümün Frozen lifecycle desteklemiyorsa yalnızca ses kapatma ve yüklemeyi durdurma yedek yöntemi kullanılır."))
        self.list = QListWidget(); root.addWidget(self.list, 1)
        row = QHBoxLayout(); sleep = QPushButton("Seçili sekmeyi uyut"); sleep.clicked.connect(self.sleep_selected); row.addWidget(sleep)
        wake = QPushButton("Seçili sekmeyi uyandır"); wake.clicked.connect(self.wake_selected); row.addWidget(wake)
        allb = QPushButton("Etkin olmayan tüm sekmeleri uyut"); allb.clicked.connect(self.sleep_inactive); row.addWidget(allb)
        done = QPushButton("Kapat"); done.clicked.connect(self.accept); row.addWidget(done); root.addLayout(row); self.refresh()

    def refresh(self):
        self.list.clear()
        for i in range(self.browser.tabs.count()):
            tab = self.browser.tabs.widget(i)
            if not isinstance(tab, BrowserTab): continue
            url = tab.view.url().toString(); state = getattr(tab, "_oss_v8_sleep_state", None)
            status = "UYKUDA" if state else ("AKTİF SEKME" if i == self.browser.tabs.currentIndex() else "Arka plan")
            self.list.addItem(QListWidgetItem(f"{status} · {self.browser.tabs.tabText(i)}\n{url}"))

    def selected_index(self):
        item = self.list.currentItem()
        if not item: return -1
        return self.list.row(item)

    def sleep_index(self, i):
        tab = self.browser.tabs.widget(i)
        if not isinstance(tab, BrowserTab) or i == self.browser.tabs.currentIndex(): return False
        if getattr(tab, "_oss_v8_sleep_state", None): return True
        state = {"url": tab.view.url().toString(), "muted": False, "native": False}
        try: state["muted"] = bool(tab.view.page().isAudioMuted())
        except Exception: pass
        try:
            lifecycle = getattr(QWebEnginePage, "LifecycleState", None)
            frozen = getattr(lifecycle, "Frozen", None) if lifecycle else None
            if frozen is not None and hasattr(tab.view.page(), "setLifecycleState"):
                tab.view.page().setLifecycleState(frozen); state["native"] = True
            else:
                tab.view.page().setAudioMuted(True); tab.view.stop()
        except Exception:
            try: tab.view.stop()
            except Exception: pass
        tab._oss_v8_sleep_state = state
        return True

    def wake_index(self, i):
        tab = self.browser.tabs.widget(i)
        if not isinstance(tab, BrowserTab): return
        state = getattr(tab, "_oss_v8_sleep_state", None)
        if not state: return
        try:
            lifecycle = getattr(QWebEnginePage, "LifecycleState", None)
            active = getattr(lifecycle, "Active", None) if lifecycle else None
            if state.get("native") and active is not None and hasattr(tab.view.page(), "setLifecycleState"):
                tab.view.page().setLifecycleState(active)
            else:
                tab.view.page().setAudioMuted(bool(state.get("muted", False)))
        except Exception: pass
        delattr(tab, "_oss_v8_sleep_state")

    def sleep_selected(self):
        i = self.selected_index()
        if i >= 0 and self.sleep_index(i): self.browser.statusBar().showMessage("Sekme uykuya alındı veya yüklemesi durduruldu.", 2500)
        elif i == self.browser.tabs.currentIndex(): QMessageBox.information(self, "Sekme uyku modu", "Önce uyutmak istediğin sekme dışındaki bir sekmeye geç.")
        self.refresh()

    def wake_selected(self):
        i = self.selected_index()
        if i >= 0: self.wake_index(i)
        self.refresh()

    def sleep_inactive(self):
        count = 0
        for i in range(self.browser.tabs.count()):
            if self.sleep_index(i): count += 1
        self.refresh(); self.browser.statusBar().showMessage(f"{count} arka plan sekmesi uyku işlemine alındı.", 3000)


class OSSSessionRecoveryDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser); self.browser = browser; self.setWindowTitle("OSS Oturum Kurtarma"); self.resize(720, 480)
        root = QVBoxLayout(self); title = QLabel("Oturum kurtarma ve kayıtlı oturumlar"); title.setObjectName("SettingsTitle"); root.addWidget(title)
        self.list = QListWidget(); root.addWidget(self.list, 1)
        row = QHBoxLayout(); recover = QPushButton("Son otomatik oturumu geri yükle"); recover.clicked.connect(self.recover_auto); row.addWidget(recover)
        saved = QPushButton("Seçili kayıtlı oturumu aç"); saved.clicked.connect(self.open_saved); row.addWidget(saved)
        save = QPushButton("Mevcut oturumu hemen kaydet"); save.clicked.connect(self.save_current); row.addWidget(save)
        done = QPushButton("Kapat"); done.clicked.connect(self.accept); row.addWidget(done); root.addLayout(row); self.refresh()

    def refresh(self):
        self.list.clear()
        auto = self.browser.data.get("session_tabs", [])
        item = QListWidgetItem(f"Son otomatik oturum · {len(auto)} sekme"); item.setData(Qt.ItemDataRole.UserRole, ("auto", "")); self.list.addItem(item)
        for name, entries in self.browser.data.get("saved_sessions", {}).items():
            item = QListWidgetItem(f"Kayıtlı oturum: {name} · {len(entries)} sekme"); item.setData(Qt.ItemDataRole.UserRole, ("saved", name)); self.list.addItem(item)
        self.list.setCurrentRow(0)

    def recover_auto(self):
        entries = self.browser.data.get("session_tabs", [])
        if not entries:
            QMessageBox.information(self, "Oturum kurtarma", "Kurtarılacak otomatik oturum bulunamadı."); return
        if QMessageBox.question(self, "Oturumu geri yükle", f"{len(entries)} sekme yeni sekmeler olarak açılsın mı?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes: return
        for entry in entries[:30]:
            if isinstance(entry, dict): url = entry.get("url", ""); pinned = bool(entry.get("pinned", False))
            else: url = str(entry); pinned = False
            if is_web_url(url): self.browser.new_tab(url, pinned=pinned)
        self.accept()

    def open_saved(self):
        item = self.list.currentItem()
        if not item: return
        kind, name = item.data(Qt.ItemDataRole.UserRole)
        if kind == "auto": self.recover_auto(); return
        entries = self.browser.data.get("saved_sessions", {}).get(name, [])
        for entry in entries[:30]:
            if isinstance(entry, dict) and is_web_url(entry.get("url", "")): self.browser.new_tab(entry["url"], pinned=bool(entry.get("pinned", False)))
        self.accept()

    def save_current(self):
        self.browser.save_session()
        self.browser.save()
        QMessageBox.information(self, "Oturum", "Geçerli otomatik oturum bilgisi kaydedildi. Kalıcı adlandırılmış oturum için oturum yöneticisini kullanabilirsin.")
        self.refresh()


# Shortcut editor also applies saved overrides after every UI creation.
_oss_v8_previous_setup_ui = MainWindow.setup_ui

def _oss_v8_setup_ui(self):
    _oss_v8_previous_setup_ui(self)
    try:
        if not getattr(self, "_oss_v8_menu_added", False):
            self._oss_v8_menu_added = True
            menu = self.tools_button.menu() if getattr(self, "tools_button", None) else None
            if menu is not None:
                menu.addSeparator()
                sub = menu.addMenu("OSS 2.0 — Gelişmiş Merkez")
                groups = [
                    ("Video Mini Oynatıcı", lambda: _oss_v8_picture_in_picture(self)),
                    ("Sekme Uyku Modu", lambda: OSSTabSleepDialog(self).exec()),
                    ("Oturum Kurtarma", lambda: OSSSessionRecoveryDialog(self).exec()),
                    ("Güvenli Parola Kasası", lambda: OSSPasswordVaultDialog(self).exec()),
                    ("Çevrimdışı Okuma Kütüphanesi", lambda: OSSOfflineLibraryDialog(self).exec()),
                    ("Akıllı Sekme Arama", lambda: OSSTabFinderDialog(self).exec()),
                    ("Güvenlik ve Bağlantı Merkezi", lambda: OSSSecurityCenterDialog(self).exec()),
                    ("Ağ Tanılama", lambda: OSSNetworkDiagnosticsDialog(self).exec()),
                    ("Geçmiş Zaman Çizelgesi", lambda: OSSTimelineDialog(self).exec()),
                    ("İki Siteyi Karşılaştır", lambda: OSSCompareSitesDialog(self).exec()),
                    ("Web Uygulaması Penceresi", lambda: _oss_v8_open_web_app(self)),
                    ("Siteye Özel Ayarlar", lambda: OSSSitePreferencesDialog(self).exec()),
                    ("Kısayol Düzenleyici", lambda: OSSShortcutEditorDialog(self).exec()),
                    ("Zamanlanmış Sayfa Yenileme", lambda: OSSScheduledTasksDialog(self).exec()),
                    ("Performans Raporu", lambda: OSSPerformanceDialog(self).exec()),
                    ("Otomatik Yedekleme", lambda: OSSAutoBackupDialog(self).exec()),
                    ("Eklenti Merkezi", lambda: OSSExtensionCenterDialog(self).exec()),
                ]
                for label, cb in groups: sub.addAction(label, cb)
            shortcuts = [
                ("OSS Video Mini Oynatıcı", "Ctrl+Shift+V", lambda: _oss_v8_picture_in_picture(self)),
                ("OSS Akıllı Sekme Arama", "Ctrl+Shift+A", lambda: OSSTabFinderDialog(self).exec()),
                ("OSS Oturum Kurtarma", "Ctrl+Shift+E", lambda: OSSSessionRecoveryDialog(self).exec()),
                ("OSS Ağ Tanılama", "Ctrl+Shift+G", lambda: OSSNetworkDiagnosticsDialog(self).exec()),
                ("OSS Güvenlik Merkezi", "Ctrl+Shift+U", lambda: OSSSecurityCenterDialog(self).exec()),
                ("OSS Performans Raporu", "Ctrl+Shift+M", lambda: OSSPerformanceDialog(self).exec()),
            ]
            self._oss_v8_default_shortcuts = {name: key for name, key, _ in shortcuts}
            for name, key, cb in shortcuts: _oss_v6_add_shortcut(self, name, key, cb)
        saved = self.data.get("settings", {}).get("custom_shortcuts", {})
        for action in getattr(self, "_oss_v6_shortcuts", []):
            if action.text() in saved:
                action.setShortcut(QKeySequence(str(saved[action.text()])))
    except Exception as exc:
        try: self.statusBar().showMessage("OSS 2.0 menüsü hazırlanamadı: " + str(exc), 3000)
        except Exception: pass

MainWindow.setup_ui = _oss_v8_setup_ui


# Integrate per-site preferences into every successful page load.
_oss_v8_previous_page_loaded = MainWindow.page_loaded

def _oss_v8_page_loaded(self, tab):
    try: _oss_v8_previous_page_loaded(self, tab)
    finally: _oss_v8_apply_site_preferences(self, tab)

MainWindow.page_loaded = _oss_v8_page_loaded



_oss_v8_previous_tab_changed = MainWindow.current_tab_changed

def _oss_v8_tab_changed(self, index):
    try: _oss_v8_previous_tab_changed(self, index)
    except Exception: pass
    try:
        tab = self.tabs.widget(index)
        if isinstance(tab, BrowserTab) and getattr(tab, "_oss_v8_sleep_state", None):
            state = tab._oss_v8_sleep_state
            lifecycle = getattr(QWebEnginePage, "LifecycleState", None)
            active = getattr(lifecycle, "Active", None) if lifecycle else None
            if state.get("native") and active is not None and hasattr(tab.view.page(), "setLifecycleState"):
                tab.view.page().setLifecycleState(active)
            else:
                tab.view.page().setAudioMuted(bool(state.get("muted", False)))
            delattr(tab, "_oss_v8_sleep_state")
    except Exception: pass

MainWindow.current_tab_changed = _oss_v8_tab_changed


# Start persistent scheduled tasks and periodic backups after original startup.
_oss_v8_previous_init = MainWindow.__init__

def _oss_v8_main_init(self, *args, **kwargs):
    _oss_v8_previous_init(self, *args, **kwargs)
    try:
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        _oss_v8_start_schedule_timer(self)
        _oss_v8_start_backup_timer(self)
    except Exception as exc:
        try: self.statusBar().showMessage("OSS 2.0 başlatma uyarısı: " + str(exc), 3500)
        except Exception: pass

MainWindow.__init__ = _oss_v8_main_init



# ============================================================
# OSS Browser 2.0.2 — Easier update source picker
# ============================================================
def _oss_update_set_url(self):
    """Let the user browse to a local latest.json instead of typing a fragile path."""
    dialog = QDialog(self)
    dialog.setWindowTitle("OSS Browser — Güncelleme Kaynağı")
    dialog.setMinimumWidth(660)
    root = QVBoxLayout(dialog)

    title = QLabel("Güncelleme kaynağını seç")
    title.setStyleSheet("font-size: 17px; font-weight: 700;")
    root.addWidget(title)
    help_text = QLabel(
        "Yerel deneme için ZIP'ten çıkardığın klasördeki updates/latest.json dosyasını seç. "
        "index.html dosyasını seçme. İnternette yayımladıysan gerçek HTTPS latest.json adresini yaz. "
        "RAR/Temp klasörü kullanma; çıkarılan klasörü kalıcı bir yere taşı."
    )
    help_text.setWordWrap(True)
    root.addWidget(help_text)

    row = QHBoxLayout()
    edit = QLineEdit(_oss_update_source(self) or "")
    edit.setPlaceholderText("https://senin-siten/updates/latest.json veya seçilen dosya yolu")
    row.addWidget(edit, 1)
    browse = QPushButton("latest.json seç…")
    row.addWidget(browse)
    root.addLayout(row)

    status = QLabel("Örnek adres değil, gerçek bir latest.json seçilmelidir.")
    status.setWordWrap(True)
    status.setObjectName("MutedLabel")
    root.addWidget(status)

    def pick_file():
        start_dir = str(Path.home())
        current = edit.text().strip()
        try:
            parsed = urlparse(current)
            if parsed.scheme == "file":
                existing = QUrl(current).toLocalFile()
                if existing and Path(existing).exists():
                    start_dir = str(Path(existing).parent)
        except Exception:
            pass
        selected, _ = QFileDialog.getOpenFileName(
            dialog,
            "Güncelleme manifesti olan latest.json dosyasını seç",
            start_dir,
            "JSON dosyası (latest.json *.json);;Tüm dosyalar (*.*)",
        )
        if selected:
            selected_path = Path(selected).resolve()
            if selected_path.name.lower() != "latest.json":
                QMessageBox.warning(dialog, "Yanlış dosya", "Lütfen index.html değil, latest.json dosyasını seç.")
                return
            try:
                import json as _json
                payload = _json.loads(selected_path.read_text(encoding="utf-8-sig"))
                if not isinstance(payload, dict) or not payload.get("version") or not payload.get("download"):
                    raise ValueError("Manifestte version veya download alanı eksik.")
            except Exception as exc:
                QMessageBox.warning(dialog, "Geçersiz manifest", f"Seçilen latest.json okunamadı veya geçersiz:\n{exc}")
                return
            edit.setText(selected_path.as_uri())
            status.setText(f"Dosya bulundu: {selected_path}\nSürüm: {payload.get('version')}")

    browse.clicked.connect(pick_file)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Save).setText("Kaydet")
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("İptal")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    root.addWidget(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    url = edit.text().strip()
    if not url:
        QMessageBox.warning(self, "Güncelleme", "Bir HTTPS adresi yaz veya latest.json dosyasını seç.")
        return
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http", "file"):
        QMessageBox.warning(self, "Güncelleme", "Adres https://, http:// veya seçilen yerel latest.json dosyasından gelmelidir.")
        return
    if parsed.scheme == "file":
        local_path = QUrl(url).toLocalFile()
        if not local_path or not Path(local_path).is_file():
            QMessageBox.warning(self, "Güncelleme", "Bu dosya bulunamadı. 'latest.json seç…' düğmesiyle gerçek dosyayı seç.")
            return
        try:
            import json as _json
            manifest = _json.loads(Path(local_path).read_text(encoding="utf-8-sig"))
            if not manifest.get("version") or not manifest.get("download"):
                raise ValueError("version/download alanı eksik")
            package_url = urljoin(url, str(manifest["download"]))
            package_path = QUrl(package_url).toLocalFile() if urlparse(package_url).scheme == "file" else ""
            if package_path and not Path(package_path).is_file():
                QMessageBox.warning(
                    self, "Güncelleme paketi bulunamadı",
                    "latest.json bulundu ancak onun işaret ettiği ZIP bulunamadı.\n\n"
                    f"Aranan ZIP:\n{package_path}\n\n"
                    "ZIP'i aynı web sitesi klasöründeki downloads klasörüne koy veya index.html üzerinden yeni paket oluştur."
                )
                return
        except Exception as exc:
            QMessageBox.warning(self, "Geçersiz manifest", f"latest.json okunamadı:\n{exc}")
            return
    elif (parsed.hostname or "").lower() in {"ornek-site.com", "example.com", "your-domain.com", "your-username.github.io"}:
        QMessageBox.warning(self, "Güncelleme", "Örnek alan adı çalışmaz. Gerçek ve yayımlanmış HTTPS adresini gir.")
        return

    _oss_update_save_source(self, url)
    QMessageBox.information(self, "Güncelleme", "Güncelleme kaynağı kaydedildi. Şimdi 'Güncellemeleri Denetle' seçeneğini kullan.")


# If no valid update source is saved, open the source chooser rather than a confusing path textbox.
_oss_update_begin_check_old_202 = _oss_update_begin_check
def _oss_update_begin_check(self, silent=False):
    if not _oss_update_source(self):
        if silent:
            return
        _oss_update_set_url(self)
        if not _oss_update_source(self):
            return
    return _oss_update_begin_check_old_202(self, silent)




# ============================================================
# OSS Browser 2.1.0 — 30 ek araç ve laboratuvar özellikleri
# ============================================================

_OSS21_ACTIVE_WORKERS = []  # Keep asynchronous workers alive until they finish.


OSS21_FEATURES = [
    ("ai", "OSS Sayfa Asistanı", "Açık sayfanın metnini çıkarır, özet taslağı ve AI istemi hazırlar."),
    ("link_preview", "Akıllı Bağlantı Önizlemesi", "Bağlantıların başlık/adres önizlemesini gösterir."),
    ("voice", "Sesle Tarayıcı Kontrolü", "İsteğe bağlı mikrofon tanıma veya yazılı komutla gezinme."),
    ("gestures", "Fare Hareketleri", "Sağ tuşla çizilen hareketlerle geri/ileri/yenile/üste git."),
    ("selection", "Seçili Metin Araçları", "Seçili metni kopyala veya seçili aram motorunda ara."),
    ("profiles", "Çoklu Hesap Profilleri", "Var olan ayrılmış tarayıcı profil yöneticisini açar."),
    ("private", "Tek Kullanımlık Oturum", "Geçici/gizli tarama sekmesi açar."),
    ("privacy_report", "Gizlilik Raporu", "Geçerli sayfanın yüklediği farklı alan adlarını listeler."),
    ("lock", "Tarayıcı Oturum Kilidi", "Ana pencereye erişimi bir uygulama PIN'i ile kilitler."),
    ("portable", "Taşınabilir Profil Yedekleme", "Ayarları ve yer imlerini JSON dosyasına aktarır/geri alır."),
    ("topic_map", "NOVA Konu Haritası", "Bir konuyla ilişkili arama terimleri ve kategori önerileri üretir."),
    ("history_suggest", "Akıllı Geçmiş Önerileri", "Yer imleri ve geçmişte sorguya uyan siteleri bulur."),
    ("document_search", "Yerel Belge Arama", "Seçilen klasörde TXT/MD/HTML/PDF dosyalarının içinde arama yapar."),
    ("similar", "Benzer Kaynaklar", "Geçmiş ve yer imlerinde geçerli sayfayla benzer kaynakları bulur."),
    ("nova_refresh", "NOVA İndeksini Güncelle", "NOVA yerel dizin taramasını başlatır."),
    ("devtools", "Web Geliştirici Araçları", "QtWebEngine destekliyorsa geliştirici araçları penceresini açar."),
    ("mobile", "Mobil Görünüm Simülatörü", "Sayfayı telefon boyutlarında ayrı pencerede açar."),
    ("speed", "Sayfa Hız Analizi", "Web Performance API ile mevcut sayfanın yükleme metriklerini gösterir."),
    ("json", "JSON / API Görüntüleyici", "JSON metnini biçimlendirir veya HTTP(S) JSON uç noktasını okur."),
    ("css", "Canlı CSS Düzenleyici", "Geçerli alana özel CSS uygular ve kaydeder."),
    ("automation", "Otomasyon Tasarımcısı", "Kaydedilmiş URL dizilerini yeni sekmelerde çalıştırır."),
    ("projects", "Proje Panoları", "Projeler içinde sayfa bağlantıları ve notlar tutar."),
    ("archive", "Web Sayfası Arşivi", "Geçerli sayfanın HTML/metnini çevrimdışı dosyaya kaydeder."),
    ("clipboard", "Pano Geçmişi", "İsteğe bağlı uygulama içi pano geçmişini tutar."),
    ("notifications", "Bildirim Merkezi", "Tarayıcı içi uyarı/hatırlatma oluşturur."),
    ("market", "OSS Araç Pazarı", "Yerleşik OSS araç kataloğunu gösterir."),
    ("diagnostics", "Tanılama Raporu", "Sürüm ve kurulumla ilgili güvenli teknik rapor üretir."),
    ("beta", "Kararlı / Beta Kanalı", "Güncelleme tercih edilen kanalını kaydeder."),
    ("usage", "Yerel Kullanım İstatistikleri", "Ziyaretleri yalnızca yerel profilde sayar."),
    ("lab", "OSS Laboratuvarı", "Deneysel bağlantı önizlemesi, hareket ve seçim araçlarını yönetir."),
]


def _oss21_cur_url(browser):
    try:
        view = browser.current_view()
        return view.url().toString() if view else ""
    except Exception:
        return ""


def _oss21_cur_title(browser):
    try:
        view = browser.current_view()
        return view.title() or _oss21_cur_url(browser) if view else ""
    except Exception:
        return _oss21_cur_url(browser)


def _oss21_text_dialog(parent, title, text, editable=False, buttons=None):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(760, 520)
    layout = QVBoxLayout(dialog)
    box = QPlainTextEdit()
    box.setPlainText(str(text or ""))
    box.setReadOnly(not editable)
    layout.addWidget(box, 1)
    row = QHBoxLayout()
    copy = QPushButton("Metni kopyala")
    copy.clicked.connect(lambda: QApplication.clipboard().setText(box.toPlainText()))
    row.addWidget(copy)
    if buttons:
        for label, callback in buttons:
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, cb=callback, field=box: cb(field.toPlainText()))
            row.addWidget(button)
    row.addStretch(1)
    close = QPushButton("Kapat")
    close.clicked.connect(dialog.accept)
    row.addWidget(close)
    layout.addLayout(row)
    return dialog, box


class OSS21FeatureCenter(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("OSS Browser 2.1 — Yeni Özellikler Merkezi")
        self.resize(850, 650)
        root = QVBoxLayout(self)
        heading = QLabel("OSS 2.1 LABORATUVARI")
        heading.setStyleSheet("font-size:20px;font-weight:800;color:#8e7dff")
        root.addWidget(heading)
        root.addWidget(QLabel("30 yeni araç ve deney. Bir özelliği seçip Aç düğmesine bas veya çift tıkla."))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Özellik ara…")
        root.addWidget(self.search)
        self.list = QListWidget()
        root.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.open_btn = QPushButton("Seçili Özelliği Aç")
        self.open_btn.clicked.connect(self.open_selected)
        row.addWidget(self.open_btn)
        close = QPushButton("Kapat")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        root.addLayout(row)
        self.search.textChanged.connect(self.refresh)
        self.list.itemDoubleClicked.connect(lambda *_: self.open_selected())
        self.refresh()

    def refresh(self):
        query = self.search.text().casefold().strip()
        self.list.clear()
        for key, title, description in OSS21_FEATURES:
            if query and query not in (title + " " + description).casefold():
                continue
            item = QListWidgetItem(f"{title}\n{description}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def open_selected(self):
        item = self.list.currentItem()
        if not item:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        QTimer.singleShot(0, lambda: _oss21_run_feature(self.browser, key))


class OSS21VoiceDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.worker = None
        self.setWindowTitle("OSS Sesle Kontrol")
        self.resize(560, 260)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Komut örnekleri: yeni sekme, geri, ileri, yenile, ana sayfa, YouTube, geçmiş, indirmeler."))
        self.command = QLineEdit()
        self.command.setPlaceholderText("Komutu yaz veya mikrofonu dene…")
        root.addWidget(self.command)
        row = QHBoxLayout()
        run = QPushButton("Komutu Çalıştır")
        run.clicked.connect(self.run_command)
        row.addWidget(run)
        self.listen_button = QPushButton("Mikrofonla Dinle")
        self.listen_button.clicked.connect(self.listen)
        row.addWidget(self.listen_button)
        root.addLayout(row)
        self.status = QLabel("Mikrofon özelliği için SpeechRecognition/PyAudio ve internet erişimi gerekebilir.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def run_command(self):
        _oss21_dispatch_voice(self.browser, self.command.text())
        self.accept()

    def listen(self):
        try:
            import speech_recognition  # noqa: F401
        except Exception:
            QMessageBox.information(self, "Mikrofon paketi eksik", "Komut İstemi'nde çalıştır:\n\npython -m pip install SpeechRecognition\n\nWindows'ta mikrofon için ayrıca uyumlu PyAudio paketi gerekebilir. Komutu kutuya yazarak da kullanabilirsin.")
            return
        self.listen_button.setEnabled(False)
        self.status.setText("Mikrofon dinleniyor… Konuş ve bekle.")
        self.worker = OSS21SpeechWorker()
        _OSS21_ACTIVE_WORKERS.append(self.worker)
        self.worker.finished.connect(lambda w=self.worker: _OSS21_ACTIVE_WORKERS.remove(w) if w in _OSS21_ACTIVE_WORKERS else None)
        self.worker.recognized.connect(self._recognized)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _recognized(self, text):
        self.command.setText(text)
        self.status.setText("Algılanan komut: " + text)
        self.listen_button.setEnabled(True)

    def _failed(self, error):
        self.status.setText("Ses tanıma başarısız: " + error)
        self.listen_button.setEnabled(True)

def _oss21_dispatch_voice(browser, raw):
    text = str(raw or "").strip().lower()
    if not text: return
    if "yeni sekme" in text: browser.new_tab()
    elif text in ("geri", "geri dön", "önceki sayfa"): browser.go_back()
    elif text in ("ileri", "ileri git"): browser.go_forward()
    elif "yenile" in text: browser.reload()
    elif "ana sayfa" in text: browser.go_home()
    elif "youtube" in text: browser.new_tab("https://www.youtube.com/")
    elif "geçmiş" in text: HistoryDialog(browser).exec()
    elif "indirme" in text: DownloadsDialog(browser).exec()
    elif "yer imi" in text: BookmarkDialog(browser).exec()
    elif "ayar" in text: browser.open_settings()
    elif "nova" in text:
        browser.data.setdefault("settings", {})["search_engine"] = NOVA_SEARCH_NAME
        browser.save(); browser.statusBar().showMessage("Varsayılan arama motoru NOVA Search olarak ayarlandı.", 2500)
    else:
        engine = browser.data.get("settings", {}).get("search_engine", "Google")
        template = SEARCH_ENGINES.get(engine) or SEARCH_ENGINES.get("Google", "https://www.google.com/search?q={}")
        browser.new_tab(template.format(quote_plus(raw)))


class OSS21AIWorker(QThread):
    answerReady = Signal(str)
    failed = Signal(str)
    def __init__(self, prompt, model, endpoint=None):
        super().__init__()
        self.prompt = prompt
        self.model = model
        self.endpoint = (endpoint or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
    def run(self):
        try:
            payload=json.dumps({"model":self.model,"prompt":self.prompt,"stream":False}).encode("utf-8")
            req=urllib.request.Request(self.endpoint+"/api/generate",data=payload,headers={"Content-Type":"application/json"},method="POST")
            with urllib.request.urlopen(req,timeout=90) as response:
                data=json.loads(response.read(8_000_000).decode("utf-8","replace"))
            answer=str(data.get("response","")).strip()
            if not answer: raise RuntimeError("Ollama boş yanıt döndürdü. Model adını kontrol et.")
            self.answerReady.emit(answer)
        except Exception as exc:
            self.failed.emit("Yerel Ollama bağlantısı başarısız: "+str(exc)+"\n\nOllama çalışıyor olmalı; model adı da bilgisayarında kurulu bir model olmalı. İstersen sayfa metnini kopyalayıp kullandığın başka bir AI hizmetine aktarabilirsin.")


def _oss21_feature_ai(browser):
    dialog, box = _oss21_text_dialog(browser, "OSS Sayfa Asistanı", "Sayfa içeriği alınıyor…", editable=True)
    box.setPlaceholderText("Açık sayfanın metni burada görünür. Yerel model ile analiz edebilir veya istemi kopyalayabilirsin.")
    view = browser.current_view()
    if view:
        view.page().runJavaScript("({title:document.title,url:location.href,text:(document.body?.innerText||'').slice(0,24000)})", lambda result: box.setPlainText("Başlık: " + str((result or {}).get("title", "")) + "\nAdres: " + str((result or {}).get("url", "")) + "\n\n" + str((result or {}).get("text", ""))) if isinstance(result, dict) else None)
    layout = dialog.layout()
    form = QFormLayout()
    model_edit = QLineEdit(os.environ.get("OSS_OLLAMA_MODEL", "llama3.2"))
    model_edit.setPlaceholderText("Kurulu Ollama modeli, ör. llama3.2")
    form.addRow("Yerel model", model_edit)
    layout.insertLayout(1, form)
    row = QHBoxLayout()
    summarize = QPushButton("Yerel özet taslağı")
    prompt_btn = QPushButton("AI istemini kopyala")
    ollama = QPushButton("Yerel Ollama ile yanıtla")
    close = QPushButton("Kapat")
    row.addWidget(summarize); row.addWidget(prompt_btn); row.addWidget(ollama); row.addWidget(close)
    layout.addLayout(row)
    status = QLabel("Harici AI kullanmadan da metni çıkarabilir. Ollama düğmesi yalnızca yerel Ollama servisine bağlanır.")
    status.setWordWrap(True); layout.insertWidget(2, status)
    def make_summary():
        text = box.toPlainText()
        lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 35]
        box.setPlainText("Yerel özet taslağı (basit metin çıkarımıdır, AI yanıtı değildir):\n\n" + "\n".join(lines[:8]))
    def copy_prompt():
        QApplication.clipboard().setText("Aşağıdaki web sayfasını Türkçe özetle. Ana fikirleri, önemli ayrıntıları ve açık belirsizlikleri belirt.\n\n" + box.toPlainText()[:18000])
        browser.statusBar().showMessage("Sayfa içeriğiyle AI istemi panoya kopyalandı.", 2500)
    def run_ollama():
        content=box.toPlainText().strip()
        model=model_edit.text().strip()
        if not content or len(content)<20:
            QMessageBox.information(dialog,"Sayfa Asistanı","Önce bir sayfa aç ve metnin yüklenmesini bekle."); return
        if not model:
            QMessageBox.information(dialog,"Yerel model","Bilgisayarında kurulu Ollama model adını yaz."); return
        prompt="Türkçe yanıt ver. Aşağıdaki web sayfasını özetle, ana noktaları maddelerle açıkla ve kullanıcı için 3 takip sorusu öner.\n\n"+content[:18000]
        ollama.setEnabled(False); status.setText("Yerel Ollama modelinden yanıt bekleniyor…")
        worker=OSS21AIWorker(prompt,model)
        _OSS21_ACTIVE_WORKERS.append(worker)
        worker.finished.connect(lambda w=worker: _OSS21_ACTIVE_WORKERS.remove(w) if w in _OSS21_ACTIVE_WORKERS else None)
        dialog._oss21_ai_worker=worker
        worker.answerReady.connect(lambda answer:(box.setPlainText(answer),status.setText("Yanıt yerel Ollama modelinden geldi."),ollama.setEnabled(True)))
        worker.failed.connect(lambda error:(status.setText(error),ollama.setEnabled(True)))
        worker.start()
    summarize.clicked.connect(make_summary); prompt_btn.clicked.connect(copy_prompt); ollama.clicked.connect(run_ollama); close.clicked.connect(dialog.accept)
    dialog.exec()


class OSS21SpeechWorker(QThread):
    recognized = Signal(str)
    failed = Signal(str)
    def run(self):
        try:
            import speech_recognition as sr
            recognizer=sr.Recognizer()
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source,duration=0.4)
                audio=recognizer.listen(source,timeout=5,phrase_time_limit=6)
            self.recognized.emit(recognizer.recognize_google(audio,language="tr-TR"))
        except Exception as exc:
            self.failed.emit(str(exc))

def _oss21_toggle_link_preview(browser):
    settings = browser.data.setdefault("settings", {})
    settings["oss21_link_preview"] = not bool(settings.get("oss21_link_preview", False))
    browser.save()
    tab = browser.current_tab()
    if tab:
        if settings["oss21_link_preview"]: _oss21_inject_link_preview(tab.view)
        else: tab.view.page().runJavaScript("window.__oss21_link_cleanup?.();document.getElementById('__oss21_link_tip')?.remove();window.__oss21_link_preview=false")
    browser.statusBar().showMessage("Bağlantı önizleme " + ("açıldı" if settings["oss21_link_preview"] else "kapatıldı"), 2200)


def _oss21_toggle_gestures(browser):
    settings = browser.data.setdefault("settings", {})
    settings["oss21_mouse_gestures"] = not bool(settings.get("oss21_mouse_gestures", False))
    browser.save()
    tab = browser.current_tab()
    if tab:
        if settings["oss21_mouse_gestures"]: _oss21_inject_gestures(tab.view)
        else: tab.view.page().runJavaScript("window.__oss21_gesture_remove?.();window.__oss21_gestures=false")
    browser.statusBar().showMessage("Fare hareketleri " + ("açıldı" if settings["oss21_mouse_gestures"] else "kapatıldı"), 2200)


def _oss21_toggle_selection_tools(browser):
    settings = browser.data.setdefault("settings", {})
    settings["oss21_selection_tools"] = not bool(settings.get("oss21_selection_tools", False))
    browser.save()
    tab = browser.current_tab()
    if tab:
        if settings["oss21_selection_tools"]: _oss21_inject_selection(tab.view, browser)
        else: tab.view.page().runJavaScript("window.__oss21_sel_cleanup?.();document.getElementById('__oss21_selbar')?.remove();window.__oss21_seltools=false")
    browser.statusBar().showMessage("Seçili metin araçları " + ("açıldı" if settings["oss21_selection_tools"] else "kapatıldı"), 2200)


def _oss21_privacy_report(browser):
    view = browser.current_view()
    if not view: return
    js = "(()=>({url:location.href,title:document.title,entries:performance.getEntriesByType('resource').map(x=>x.name).filter(Boolean).slice(0,120),cookiesEnabled:navigator.cookieEnabled,https:location.protocol==='https:'}))()"
    def done(result):
        data = result if isinstance(result, dict) else {}
        host = (urlparse(str(data.get('url',''))).hostname or '').lower()
        hosts = sorted({(urlparse(u).hostname or '').lower() for u in data.get('entries', []) if urlparse(u).hostname})
        lines = [f"Başlık: {data.get('title','')}", f"Adres: {data.get('url','')}", f"HTTPS: {data.get('https', False)}", f"Çerezler etkin: {data.get('cookiesEnabled', False)}", f"İstek listesinde görülen alan adı: {len(hosts)}", "", "Alan adları:"] + ["• " + h + (" (ana sayfa)" if h == host else "") for h in hosts]
        _oss21_text_dialog(browser, "OSS Gizlilik Raporu", "\n".join(lines))[0].exec()
    view.page().runJavaScript(js, done)


def _oss21_session_lock(browser):
    settings = browser.data.setdefault("settings", {})
    current_hash = settings.get("oss21_lock_hash", "")
    if not current_hash:
        one, ok = QInputDialog.getText(browser, "Oturum Kilidi Kur", "Yeni PIN/parola oluştur:", QLineEdit.EchoMode.Password)
        if not ok or len(one) < 4:
            QMessageBox.information(browser, "Oturum kilidi", "En az 4 karakterli bir PIN/parola seçmelisin."); return
        two, ok = QInputDialog.getText(browser, "Oturum Kilidi Kur", "PIN/parolayı tekrar yaz:", QLineEdit.EchoMode.Password)
        if not ok or one != two:
            QMessageBox.warning(browser, "Oturum kilidi", "Parolalar eşleşmedi."); return
        settings["oss21_lock_hash"] = hashlib.sha256(one.encode("utf-8")).hexdigest(); browser.save(); current_hash = settings["oss21_lock_hash"]
    dlg = QDialog(browser); dlg.setWindowTitle("OSS Oturum Kilitlendi"); dlg.setWindowModality(Qt.WindowModality.ApplicationModal); dlg.setFixedSize(390, 170)
    layout = QVBoxLayout(dlg); layout.addWidget(QLabel("OSS Browser oturumu kilitlendi. Devam etmek için PIN/parolanı gir."))
    field = QLineEdit(); field.setEchoMode(QLineEdit.EchoMode.Password); field.setPlaceholderText("PIN / parola"); layout.addWidget(field)
    message = QLabel(""); layout.addWidget(message)
    buttons = QHBoxLayout(); unlock = QPushButton("Kilidi Aç"); clear = QPushButton("Kilit parolasını sıfırla"); buttons.addWidget(unlock); buttons.addWidget(clear); layout.addLayout(buttons)
    def try_unlock():
        if hashlib.sha256(field.text().encode("utf-8")).hexdigest() == settings.get("oss21_lock_hash"):
            dlg.accept()
        else: message.setText("Parola yanlış.")
    def reset():
        ans = QMessageBox.question(dlg, "Parolayı sıfırla", "Kilit parolasını kaldırmak için sıfırlama yapılsın mı? Bu işlem geçerli kilidi kaldırır.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ans == QMessageBox.StandardButton.Yes:
            settings.pop("oss21_lock_hash", None); browser.save(); dlg.accept()
    unlock.clicked.connect(try_unlock); field.returnPressed.connect(try_unlock); clear.clicked.connect(reset); dlg.exec()


def _oss21_portable_profile(browser):
    box = QMessageBox(browser); box.setWindowTitle("Taşınabilir Profil"); box.setText("Ayarlar, yer imleri, geçmiş ve çalışma alanlarını JSON dosyasına aktarabilir veya içeri alabilirsin. Şifre kasası ayrı, Windows DPAPI ile korunduğu için buraya dahil edilmez.")
    exp = box.addButton("Dışa Aktar", QMessageBox.ButtonRole.AcceptRole); imp = box.addButton("İçe Aktar", QMessageBox.ButtonRole.ActionRole); box.addButton("Kapat", QMessageBox.ButtonRole.RejectRole); box.exec()
    if box.clickedButton() == exp:
        path, _ = QFileDialog.getSaveFileName(browser, "OSS profil yedeğini kaydet", str(Path.home() / "OSS-profile.json"), "JSON (*.json)")
        if path:
            payload = dict(browser.data); payload.pop("password_vault", None); payload.pop("vault", None)
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            QMessageBox.information(browser, "Taşınabilir Profil", "Profil yedeği kaydedildi:\n" + path)
    elif box.clickedButton() == imp:
        path, _ = QFileDialog.getOpenFileName(browser, "OSS profil yedeğini seç", str(Path.home()), "JSON (*.json)")
        if not path: return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(payload, dict): raise ValueError("JSON nesnesi bekleniyor")
            ans = QMessageBox.question(browser, "Profil içe aktar", "Geçerli tarayıcı verileri yedek dosyasındaki verilerle değiştirilsin mi? Önce yedek alman önerilir.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans == QMessageBox.StandardButton.Yes:
                browser.data = payload; browser.data.setdefault("settings", {}); browser.save(); browser.refresh_home_pages(); QMessageBox.information(browser, "Profil", "İçe aktarıldı. Bazı açık sekmeleri yenilemen gerekebilir.")
        except Exception as exc: QMessageBox.warning(browser, "Profil içe aktarma", str(exc))


def _oss21_topic_map(browser):
    topic, ok = QInputDialog.getText(browser, "NOVA Konu Haritası", "Konu:", text="Python")
    if not ok or not topic.strip(): return
    words = [w for w in re.findall(r"[\wğüşöçıİĞÜŞÖÇ-]+", topic.lower()) if len(w) > 2][:6]
    related = {
        "python": ["Python kurulumu", "PySide6", "pip paketleri", "Python projeleri", "hata ayıklama"],
        "minecraft": ["Minecraft modları", "Forge", "OptiFine", "sunucular", "kaynak paketleri"],
        "bilim": ["uzay", "fizik", "astronomi", "araştırmalar", "NASA"],
        "web": ["HTML", "CSS", "JavaScript", "HTTP", "web güvenliği"],
        "teknoloji": ["yazılım", "donanım", "siber güvenlik", "yapay zekâ", "açık kaynak"],
    }
    key = next((k for k in related if k in topic.lower()), "")
    nodes = related.get(key, [topic + " rehberi", topic + " haberleri", topic + " kaynakları", topic + " sorun giderme", topic + " inceleme"])
    lines = [f"NOVA KONU HARİTASI: {topic}", "", "Merkez konu", "    ↓", "  [" + topic + "]", "    ├── " + "\n    ├── ".join(nodes[:4]), "    └── " + nodes[-1], "", "Önerilen sorgular:"] + ["• " + " ".join([topic] + [w]) for w in nodes]
    dialog, text = _oss21_text_dialog(browser, "NOVA Konu Haritası", "\n".join(lines))
    search = QPushButton("İlk öneriyi seçili motorla ara")
    search.clicked.connect(lambda: (browser.new_tab((SEARCH_ENGINES.get(browser.data.get('settings',{}).get('search_engine','Google')) or SEARCH_ENGINES['Google']).format(quote_plus(topic + ' ' + nodes[0]))), dialog.accept()))
    dialog.layout().itemAt(1).layout().insertWidget(0, search) if dialog.layout().count() > 1 and dialog.layout().itemAt(1).layout() else None
    dialog.exec()


def _oss21_history_suggest(browser):
    dlg = QDialog(browser); dlg.setWindowTitle("Akıllı Geçmiş Önerileri"); dlg.resize(720, 520); layout = QVBoxLayout(dlg)
    query = QLineEdit(); query.setPlaceholderText("Başlık veya URL ara…"); layout.addWidget(query)
    items = QListWidget(); layout.addWidget(items, 1)
    def refresh():
        items.clear(); q = query.text().casefold().strip(); rows = []
        for row in browser.data.get("history", [])[-1500:]:
            if isinstance(row, dict):
                title, url = str(row.get("title", "")), str(row.get("url", row.get("address", "")))
            else: continue
            if is_web_url(url) and (not q or q in title.casefold() or q in url.casefold()): rows.append((title or url, url))
        for row in browser.data.get("bookmarks", []):
            if isinstance(row, dict):
                title, url = str(row.get("title", "")), str(row.get("url", ""))
                if is_web_url(url) and (not q or q in title.casefold() or q in url.casefold()): rows.append((title or url, url))
        seen=set()
        for title,url in reversed(rows):
            if url in seen: continue
            seen.add(url); it=QListWidgetItem(title + "\n" + url); it.setData(Qt.ItemDataRole.UserRole,url); items.addItem(it)
        if items.count(): items.setCurrentRow(0)
    def open_row():
        it=items.currentItem()
        if it: browser.new_tab(it.data(Qt.ItemDataRole.UserRole)); dlg.accept()
    query.textChanged.connect(refresh); items.itemDoubleClicked.connect(lambda *_:open_row()); query.returnPressed.connect(open_row)
    btn=QPushButton("Seçileni aç"); btn.clicked.connect(open_row); layout.addWidget(btn); refresh(); dlg.exec()


def _oss21_document_search(browser):
    folder = QFileDialog.getExistingDirectory(browser, "Belgelerin aranacağı klasörü seç", str(Path.home()))
    if not folder: return
    query, ok = QInputDialog.getText(browser, "Yerel Belge Arama", "Aranacak ifade:")
    if not ok or not query.strip(): return
    q=query.casefold(); results=[]; scanned=0
    for path in Path(folder).rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".txt", ".md", ".html", ".htm", ".py", ".json", ".csv", ".log", ".pdf"}: continue
        if scanned >= 500: break
        scanned+=1
        try:
            if path.suffix.lower()==".pdf":
                try:
                    from pypdf import PdfReader
                    reader=PdfReader(str(path)); content="\n".join((p.extract_text() or "") for p in reader.pages[:60])
                except Exception: continue
            else: content=path.read_text(encoding="utf-8", errors="ignore")[:1000000]
            ix=content.casefold().find(q)
            if ix>=0:
                snippet=re.sub(r"\s+", " ", content[max(0,ix-90):ix+len(q)+140]).strip()
                results.append(f"{path}\n  …{snippet}…")
        except Exception: pass
    body=f"Klasör: {folder}\nTaranan dosya: {scanned}\nEşleşme: {len(results)}\n\n"+"\n\n".join(results[:300])
    _oss21_text_dialog(browser,"Yerel Belge Arama",body).exec()


def _oss21_similar_sources(browser):
    title=_oss21_cur_title(browser); url=_oss21_cur_url(browser); host=(urlparse(url).hostname or "").lower()
    tokens={t for t in re.findall(r"[\wğüşöçıİĞÜŞÖÇ-]+", title.casefold()) if len(t)>3}
    rows=[]
    for row in browser.data.get("history", [])[-1200:]:
        if isinstance(row,dict):
            t=str(row.get("title","")); u=str(row.get("url",row.get("address","")))
            if not is_web_url(u) or u==url: continue
            overlap=len(tokens & {x for x in re.findall(r"[\wğüşöçıİĞÜŞÖÇ-]+",t.casefold()) if len(x)>3})
            if overlap or (host and urlparse(u).hostname==host): rows.append((overlap,t or u,u))
    for row in browser.data.get("bookmarks",[]):
        if isinstance(row,dict):
            t=str(row.get("title","")); u=str(row.get("url",""))
            if is_web_url(u) and u!=url and (tokens & set(re.findall(r"[\wğüşöçıİĞÜŞÖÇ-]+",t.casefold()))): rows.append((1,t or u,u))
    rows=sorted(rows,key=lambda x:x[0],reverse=True)[:150]
    _oss21_text_dialog(browser,"Benzer Kaynaklar",f"Geçerli sayfa: {title}\n{url}\n\nYerel geçmiş/yer imleri içindeki olası benzer kaynaklar:\n\n"+"\n".join(f"[{n}] {t}\n{u}" for n,t,u in rows) if rows else f"Geçerli sayfa: {title}\n{url}\n\nYerel geçmiş/yer imlerinde benzer kaynak bulunamadı.")[0].exec()


def _oss21_nova_refresh(browser):
    try:
        started = _nova_start_crawler(browser, force=True)
        if not started:
            QMessageBox.information(browser,"NOVA Search","NOVA tarayıcısı zaten çalışıyor olabilir veya yeni tarama başlatılamadı.")
    except Exception as exc:
        QMessageBox.warning(browser,"NOVA Search","Dizin güncellemesi başlatılamadı:\n"+str(exc))


def _oss21_devtools(browser):
    view=browser.current_view()
    if not view: return
    try:
        dlg=QDialog(browser); dlg.setWindowTitle("OSS Web Geliştirici Araçları"); dlg.resize(1050,720); layout=QVBoxLayout(dlg)
        dev=QWebEngineView(dlg); page=QWebEnginePage(browser.browser_profile,dev); dev.setPage(page)
        view.page().setDevToolsPage(page)
        layout.addWidget(dev,1); close=QPushButton("Kapat"); close.clicked.connect(dlg.accept); layout.addWidget(close)
        browser._oss21_devtools_dialog=dlg; browser._oss21_devtools_view=dev
        dlg.show()
    except Exception as exc:
        QMessageBox.warning(browser,"Geliştirici araçları", "QtWebEngine bu geliştirici araçları bağlantısını desteklemiyor olabilir.\n\n"+str(exc))


def _oss21_mobile_view(browser):
    url=_oss21_cur_url(browser)
    if not is_web_url(url): url="https://www.wikipedia.org/"
    dlg=QDialog(browser); dlg.setWindowTitle("OSS Mobil Görünüm — 390 × 844"); dlg.setFixedSize(430,910); layout=QVBoxLayout(dlg)
    bar=QHBoxLayout(); address=QLineEdit(url); go=QPushButton("Git"); bar.addWidget(address,1); bar.addWidget(go); layout.addLayout(bar)
    view=QWebEngineView(dlg); page=QWebEnginePage(browser.browser_profile,view); view.setPage(page); layout.addWidget(view,1)
    go.clicked.connect(lambda: view.setUrl(QUrl(address.text().strip() if is_web_url(address.text().strip()) else "https://"+address.text().strip())))
    address.returnPressed.connect(lambda:go.click()); view.setUrl(QUrl(url)); dlg.exec()


def _oss21_speed(browser):
    view=browser.current_view()
    if not view: return
    js="(()=>{const n=performance.getEntriesByType('navigation')[0];const rs=performance.getEntriesByType('resource');return {url:location.href,title:document.title,domReady:n?Math.round(n.domContentLoadedEventEnd):null,load:n?Math.round(n.loadEventEnd):null,response:n?Math.round(n.responseEnd):null,resources:rs.length,transfer:rs.reduce((a,x)=>a+(x.transferSize||0),0),failed:rs.filter(x=>x.duration===0).length}})()"
    def done(d):
        d=d if isinstance(d,dict) else {}
        report=(f"Başlık: {d.get('title','')}\nAdres: {d.get('url','')}\nDOM hazır olma: {d.get('domReady','—')} ms\nLoad olayı: {d.get('load','—')} ms\nİlk yanıt sonu: {d.get('response','—')} ms\nKaynak sayısı: {d.get('resources',0)}\nTarayıcının bildirdiği aktarım: {d.get('transfer',0):,} bayt\n\nNot: Önbellek, sayfa dinamikliği ve tarayıcı sınırlamaları sonuçları etkiler; aktarım boyutu her kaynağı kapsamayabilir.")
        _oss21_text_dialog(browser,"Sayfa Hız Analizi",report)[0].exec()
    view.page().runJavaScript(js,done)


class OSS21JSONDialog(QDialog):
    def __init__(self,browser):
        super().__init__(browser); self.browser=browser; self.setWindowTitle("OSS JSON / API Görüntüleyici"); self.resize(820,620)
        root=QVBoxLayout(self); root.addWidget(QLabel("JSON metni yapıştır veya HTTP(S) JSON adresi gir. Yalnızca erişilebilir ve izinli uç noktaları kullan."))
        row=QHBoxLayout(); self.url=QLineEdit(); self.url.setPlaceholderText("https://.../api/data.json"); load=QPushButton("URL'den yükle"); load.clicked.connect(self.load_url); row.addWidget(self.url,1); row.addWidget(load); root.addLayout(row)
        self.box=QPlainTextEdit(); self.box.setPlaceholderText('{"ok": true}'); root.addWidget(self.box,1)
        row=QHBoxLayout(); fmt=QPushButton("Biçimlendir / Doğrula"); fmt.clicked.connect(self.format_json); row.addWidget(fmt); save=QPushButton("JSON kaydet"); save.clicked.connect(self.save_json); row.addWidget(save); close=QPushButton("Kapat"); close.clicked.connect(self.accept); row.addWidget(close); root.addLayout(row)
    def format_json(self):
        try: self.box.setPlainText(json.dumps(json.loads(self.box.toPlainText()),ensure_ascii=False,indent=2))
        except Exception as exc: QMessageBox.warning(self,"Geçersiz JSON",str(exc))
    def save_json(self):
        self.format_json(); path,_=QFileDialog.getSaveFileName(self,"JSON kaydet",str(DOWNLOAD_DIR/"oss-data.json"),"JSON (*.json)")
        if path: Path(path).write_text(self.box.toPlainText(),encoding="utf-8")
    def load_url(self):
        url=self.url.text().strip()
        if not urlparse(url).scheme in ("http","https") or not urlparse(url).netloc: QMessageBox.warning(self,"URL","HTTP(S) adresi gir."); return
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"OSS-Browser-JSON-Viewer/1.0"})
            with urllib.request.urlopen(req,timeout=8) as res: data=res.read(2_000_000).decode("utf-8","replace")
            obj=json.loads(data); self.box.setPlainText(json.dumps(obj,ensure_ascii=False,indent=2))
        except Exception as exc: QMessageBox.warning(self,"API/JSON yüklenemedi",str(exc))


def _oss21_css_editor(browser):
    url=_oss21_cur_url(browser); host=(urlparse(url).hostname or "").lower()
    if not host: QMessageBox.information(browser,"CSS Düzenleyici","Önce HTTP(S) sayfası aç."); return
    saved=browser.data.setdefault("site_css",{}).get(host,"")
    dlg=QDialog(browser); dlg.setWindowTitle("Canlı CSS Düzenleyici — "+host); dlg.resize(760,520); layout=QVBoxLayout(dlg)
    layout.addWidget(QLabel("CSS yalnızca şu anda açık olan alan adına uygulanır. Bazı siteler stilleri yeniden yazabilir."))
    box=QPlainTextEdit(); box.setPlainText(saved or "body { font-family: Segoe UI, sans-serif !important; }\n"); layout.addWidget(box,1)
    row=QHBoxLayout(); view=browser.current_view()
    def apply():
        css=box.toPlainText()[:20000]
        js="(()=>{let s=document.getElementById('__oss21_custom_css');if(!s){s=document.createElement('style');s.id='__oss21_custom_css';document.documentElement.appendChild(s)}s.textContent="+json.dumps(css)+"})()"
        if view: view.page().runJavaScript(js)
    def save():
        browser.data.setdefault("site_css",{})[host]=box.toPlainText()[:20000]; browser.save(); apply(); QMessageBox.information(dlg,"CSS","Bu alan adı için CSS kaydedildi.")
    for label,fn in [("Canlı uygula",apply),("Kaydet",save),("Kapat",dlg.accept)]:
        b=QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
    layout.addLayout(row); dlg.exec()


def _oss21_automation(browser):
    dlg=QDialog(browser); dlg.setWindowTitle("OSS Otomasyon Tasarımcısı"); dlg.resize(720,540); layout=QVBoxLayout(dlg)
    routines=browser.data.setdefault("automations",{})
    row=QHBoxLayout(); name=QLineEdit(); name.setPlaceholderText("Otomasyon adı: Sabah araştırması"); row.addWidget(name,1); layout.addLayout(row)
    box=QPlainTextEdit(); box.setPlaceholderText("Her satıra bir HTTP(S) adresi yaz. Çalıştırıldığında her adres ayrı sekmede açılır."); layout.addWidget(box,1)
    listing=QListWidget(); layout.addWidget(listing,1)
    def refresh(): listing.clear(); [listing.addItem(k) for k in routines]
    def load():
        it=listing.currentItem()
        if it: name.setText(it.text()); box.setPlainText("\n".join(routines.get(it.text(),[])))
    def save():
        n=name.text().strip(); urls=[x.strip() for x in box.toPlainText().splitlines() if x.strip()]
        urls=[u if urlparse(u).scheme else "https://"+u for u in urls]
        if not n or not urls or any(not is_web_url(u) for u in urls): QMessageBox.warning(dlg,"Otomasyon","Ad gir ve her satıra geçerli bir URL yaz."); return
        routines[n]=urls[:30]; browser.save(); refresh(); QMessageBox.information(dlg,"Otomasyon",f"'{n}' kaydedildi.")
    def run():
        it=listing.currentItem(); n=it.text() if it else name.text().strip(); urls=routines.get(n,[])
        if not urls: save(); urls=routines.get(name.text().strip(),[])
        for u in urls[:30]: browser.new_tab(u)
        dlg.accept()
    buttons=QHBoxLayout()
    for label,fn in [("Seçileni yükle",load),("Kaydet",save),("Çalıştır",run),("Kapat",dlg.accept)]:
        b=QPushButton(label); b.clicked.connect(fn); buttons.addWidget(b)
    layout.addLayout(buttons); listing.itemDoubleClicked.connect(lambda *_:load()); refresh(); dlg.exec()


def _oss21_project_boards(browser):
    projects=browser.data.setdefault("project_boards",{})
    dlg=QDialog(browser); dlg.setWindowTitle("OSS Proje Panoları"); dlg.resize(780,580); root=QVBoxLayout(dlg)
    row=QHBoxLayout(); names=QComboBox(); names.addItems(list(projects) or ["Genel"]); row.addWidget(names,1); new=QPushButton("Yeni Proje"); row.addWidget(new); root.addLayout(row)
    notes=QPlainTextEdit(); notes.setPlaceholderText("Proje notları, yapılacak işler, kaynaklar…"); root.addWidget(notes,1)
    urls=QListWidget(); root.addWidget(urls,1)
    def ensure():
        n=names.currentText() or "Genel"; projects.setdefault(n,{"notes":"","urls":[]}); return projects[n]
    def refresh():
        p=ensure(); notes.setPlainText(p.get("notes","")); urls.clear()
        for u in p.get("urls",[]): urls.addItem(u)
    def save():
        p=ensure(); p["notes"]=notes.toPlainText()[:30000]; browser.save(); browser.statusBar().showMessage("Proje panosu kaydedildi.",2000)
    def add_current():
        u=_oss21_cur_url(browser)
        if is_web_url(u):
            p=ensure();
            if u not in p["urls"]: p["urls"].append(u); refresh(); browser.save()
    def open_url():
        it=urls.currentItem()
        if it: browser.new_tab(it.text())
    def create():
        n,ok=QInputDialog.getText(dlg,"Yeni proje","Proje adı:")
        if ok and n.strip():
            if n.strip() in projects: QMessageBox.information(dlg,"Proje","Bu ad zaten var."); return
            projects[n.strip()]={"notes":"","urls":[]}; names.addItem(n.strip()); names.setCurrentText(n.strip()); refresh(); browser.save()
    names.currentTextChanged.connect(lambda *_:refresh()); new.clicked.connect(create)
    row=QHBoxLayout()
    for label,fn in [("Notları kaydet",save),("Geçerli sayfayı ekle",add_current),("Seçileni aç",open_url),("Kapat",dlg.accept)]:
        b=QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
    root.addLayout(row); refresh(); dlg.exec()


def _oss21_archive_page(browser):
    view=browser.current_view()
    if not view: return
    proposed="oss-page-"+datetime.now().strftime("%Y%m%d-%H%M%S")+".html"
    path,_=QFileDialog.getSaveFileName(browser,"Web sayfasını arşivle",str(DOWNLOAD_DIR/proposed),"HTML (*.html);;TXT (*.txt)")
    if not path:return
    is_txt=path.lower().endswith(".txt")
    js="({url:location.href,title:document.title,html:document.documentElement.outerHTML,text:document.body?.innerText||''})"
    def done(data):
        try:
            data=data if isinstance(data,dict) else {}
            if is_txt:
                content=f"{data.get('title','')}\n{data.get('url','')}\n\n{data.get('text','')}"
            else:
                content="<!-- OSS Archive URL: "+html.escape(str(data.get('url','')))+" -->\n"+str(data.get('html',''))
            Path(path).write_text(content,encoding="utf-8")
            QMessageBox.information(browser,"Sayfa arşivi","Kaydedildi:\n"+path+"\n\nNot: Bu işlem sayfanın mevcut HTML/metnini saklar; dinamik içerikler, girişler ve sunucu tarafı işlevler arşivde çalışmayabilir.")
        except Exception as exc: QMessageBox.warning(browser,"Arşiv kaydetme",str(exc))
    view.page().runJavaScript(js,done)


def _oss21_clipboard(browser):
    settings=browser.data.setdefault("settings",{}); settings.setdefault("clipboard_history_enabled",False)
    dlg=QDialog(browser); dlg.setWindowTitle("OSS Pano Geçmişi"); dlg.resize(680,480); root=QVBoxLayout(dlg)
    chk=QCheckBox("Pano geçmişini etkinleştir (kopyalanan metinler bu bilgisayarda saklanır)"); chk.setChecked(bool(settings.get("clipboard_history_enabled"))); root.addWidget(chk)
    lst=QListWidget(); root.addWidget(lst,1)
    def refresh():
        lst.clear()
        for t in settings.get("clipboard_history",[])[:200]: lst.addItem(str(t)[:300].replace("\n"," "))
    def on_enabled(value):
        settings["clipboard_history_enabled"]=value; browser.save()
        if value and not getattr(browser,"_oss21_clipboard_connected",False):
            QApplication.clipboard().dataChanged.connect(lambda: _oss21_record_clipboard(browser)); browser._oss21_clipboard_connected=True
    def copy_selected():
        i=lst.currentRow(); hist=settings.get("clipboard_history",[])
        if 0<=i<len(hist): QApplication.clipboard().setText(hist[i])
    def clear(): settings["clipboard_history"]=[]; browser.save(); refresh()
    chk.toggled.connect(on_enabled)
    row=QHBoxLayout()
    for label,fn in [("Seçileni kopyala",copy_selected),("Geçmişi temizle",clear),("Kapat",dlg.accept)]:
        b=QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
    root.addLayout(row); refresh(); dlg.exec()
    if settings.get("clipboard_history_enabled") and not getattr(browser,"_oss21_clipboard_connected",False):
        QApplication.clipboard().dataChanged.connect(lambda: _oss21_record_clipboard(browser)); browser._oss21_clipboard_connected=True


def _oss21_record_clipboard(browser):
    try:
        settings=browser.data.setdefault("settings",{})
        if not settings.get("clipboard_history_enabled"): return
        text=QApplication.clipboard().text()
        if not text or len(text)>8000 or text==settings.get("clipboard_last"): return
        settings["clipboard_last"]=text
        hist=settings.setdefault("clipboard_history",[])
        hist.insert(0,text); del hist[200:]
        # Reduce disk writes: save only when a new record appears.
        browser.save()
    except Exception: pass


def _oss21_notifications(browser):
    msg,ok=QInputDialog.getMultiLineText(browser,"OSS Bildirim Merkezi","Bildirim metni:","")
    if not ok or not msg.strip(): return
    settings=browser.data.setdefault("settings",{})
    rows=settings.setdefault("oss_notifications",[]); rows.insert(0,{"text":msg[:1500],"time":datetime.now().isoformat(timespec="seconds")}); del rows[100:]
    browser.save(); QMessageBox.information(browser,"OSS Bildirim Merkezi",msg.strip()[:1500])


def _oss21_market(browser):
    rows=[
        ("Sayfa Asistanı","Sayfa metnini al ve özet taslağı oluştur."),("Bağlantı Önizleme","Link üstünde başlık ve URL göster."),("Fare Hareketleri","Sağ tuşla sayfada gezin."),("Seçili Metin Araçları","Metni kopyala veya ara."),("JSON Görüntüleyici","JSON biçimlendir ve doğrula."),("CSS Düzenleyici","Alan adına özel CSS kaydet."),("Proje Panoları","Kaynakları ve notları grupla."),("Belge Arama","Yerel belgelerin içinde arama yap."),("Gizlilik Raporu","Sayfanın kaynak alan adlarını görüntüle."),("Tanılama","Güvenli teknik rapor oluştur.")]
    _oss21_text_dialog(browser,"OSS Araç Pazarı — Yerleşik araçlar", "OSS 2.1 ile birlikte gelen yerleşik araç kataloğu. Bu katalog şu an çevrimiçi mağaza değil; eklentileri doğrulanmamış kaynaklardan otomatik yüklemez.\n\n"+"\n".join(f"• {n}: {d}" for n,d in rows))[0].exec()


def _oss21_diagnostics(browser):
    view=browser.current_view(); url=_oss21_cur_url(browser)
    payload={"app":APP_NAME,"version":APP_VERSION,"python":sys.version,"platform":sys.platform,"app_dir":str(APP_DIR),"data_file_exists":DATA_FILE.exists(),"data_file_size":DATA_FILE.stat().st_size if DATA_FILE.exists() else 0,"current_url":url,"history_entries":len(browser.data.get("history",[])),"bookmarks":len(browser.data.get("bookmarks",[])),"tabs":browser.tabs.count() if hasattr(browser,"tabs") else 0,"psutil_available":psutil is not None,"qtwebengine":"loaded","timestamp":datetime.now().isoformat(timespec="seconds")}
    report=json.dumps(payload,ensure_ascii=False,indent=2)
    box=QMessageBox(browser); box.setWindowTitle("OSS Tanılama Raporu"); box.setText("Tanılama raporu hazır. URL ve yerel yollar kişisel bilgi içerebilir; paylaşmadan önce gözden geçir."); box.setDetailedText(report); box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Close)
    result=box.exec()
    if result==QMessageBox.StandardButton.Save:
        path,_=QFileDialog.getSaveFileName(browser,"Tanılama raporunu kaydet",str(DOWNLOAD_DIR/"oss-diagnostics.json"),"JSON (*.json)")
        if path: Path(path).write_text(report,encoding="utf-8")


def _oss21_beta(browser):
    settings=browser.data.setdefault("settings",{})
    dlg=QDialog(browser); dlg.setWindowTitle("OSS Güncelleme Kanalı"); dlg.setMinimumWidth(650); root=QVBoxLayout(dlg)
    root.addWidget(QLabel("Kararlı kanal önerilir. Beta manifesti varsa URL'yi buraya yazabilirsin. Boş beta URL'si mevcut kaynak adresini değiştirmez."))
    form=QFormLayout(); root.addLayout(form)
    combo=QComboBox(); combo.addItem("Kararlı (önerilen)","stable"); combo.addItem("Beta / Deneysel","beta"); i=combo.findData(settings.get("update_channel","stable")); combo.setCurrentIndex(max(0,i))
    beta_url=QLineEdit(str(settings.get("beta_update_url",""))); beta_url.setPlaceholderText("https://senin-siten/updates/beta.json")
    stable_url=QLineEdit(str(settings.get("stable_update_url",settings.get("update_url","")))); stable_url.setPlaceholderText("Mevcut latest.json kaynağı")
    form.addRow("Güncelleme kanalı",combo); form.addRow("Kararlı manifest",stable_url); form.addRow("Beta manifest",beta_url)
    row=QHBoxLayout(); save=QPushButton("Kaydet ve uygula"); close=QPushButton("Kapat"); row.addWidget(save); row.addWidget(close); root.addLayout(row)
    def persist():
        channel=combo.currentData(); stable=stable_url.text().strip(); beta=beta_url.text().strip()
        for label,url in (("Kararlı",stable),("Beta",beta)):
            if url and urlparse(url).scheme not in ("https","http","file"):
                QMessageBox.warning(dlg,"Manifest adresi",f"{label} URL'si https://, http:// veya seçilmiş bir file:/// adresi olmalı."); return
        settings["stable_update_url"]=stable; settings["beta_update_url"]=beta; settings["update_channel"]=channel
        chosen=beta if channel=="beta" and beta else stable if channel=="stable" and stable else settings.get("update_url","")
        if chosen: settings["update_url"]=chosen
        browser.save(); QMessageBox.information(dlg,"Güncelleme kanalı","Kanal tercihi kaydedildi. Yeni manifesti kullanmak için 'Güncellemeleri Denetle' seçeneğini çalıştır."); dlg.accept()
    save.clicked.connect(persist); close.clicked.connect(dlg.reject); dlg.exec()

def _oss21_usage(browser):
    data=browser.data.setdefault("oss21_usage",{})
    domains=data.get("domains",{})
    rows=sorted(domains.items(),key=lambda x:x[1],reverse=True)
    report="OSS Yerel Kullanım İstatistikleri\n"+f"Toplam sayfa yüklemesi: {data.get('visits',0)}\nFarklı alan adı: {len(domains)}\n\nEn çok ziyaret edilen alan adları:\n"+"\n".join(f"{n+1}. {host}: {count}" for n,(host,count) in enumerate(rows[:100]))
    _oss21_text_dialog(browser,"Yerel Kullanım İstatistikleri",report)[0].exec()


def _oss21_lab(browser):
    settings=browser.data.setdefault("settings",{})
    dlg=QDialog(browser); dlg.setWindowTitle("OSS Laboratuvarı"); dlg.resize(550,330); root=QVBoxLayout(dlg)
    root.addWidget(QLabel("Deneysel özellikleri açıp kapat. Bunlar yalnızca OSS Browser içinde çalışır."))
    items=[("oss21_link_preview","Akıllı bağlantı önizleme"),("oss21_mouse_gestures","Fare hareketleri"),("oss21_selection_tools","Seçili metin araçları"),("oss21_usage_enabled","Yerel kullanım istatistikleri"),("clipboard_history_enabled","Pano geçmişi (metinler yerel saklanır)")]
    boxes=[]
    for key,label in items:
        check=QCheckBox(label); check.setChecked(bool(settings.get(key,False))); root.addWidget(check); boxes.append((key,check))
    def save():
        old={k:bool(settings.get(k,False)) for k,_ in boxes}
        for k,c in boxes: settings[k]=c.isChecked()
        browser.save()
        # Apply interactive browser scripts immediately on the current page.
        for k,_ in boxes:
            if old[k]!=bool(settings[k]):
                if k=="oss21_link_preview": _oss21_apply_page_tools(browser,browser.current_tab())
                elif k=="oss21_mouse_gestures": _oss21_apply_page_tools(browser,browser.current_tab())
                elif k=="oss21_selection_tools": _oss21_apply_page_tools(browser,browser.current_tab())
        if settings.get("clipboard_history_enabled") and not getattr(browser,"_oss21_clipboard_connected",False):
            QApplication.clipboard().dataChanged.connect(lambda: _oss21_record_clipboard(browser)); browser._oss21_clipboard_connected=True
        QMessageBox.information(dlg,"OSS Laboratuvarı","Deney tercihleri kaydedildi."); dlg.accept()
    row=QHBoxLayout(); savebtn=QPushButton("Kaydet ve uygula"); savebtn.clicked.connect(save); row.addWidget(savebtn); close=QPushButton("Kapat"); close.clicked.connect(dlg.reject); row.addWidget(close); root.addLayout(row); dlg.exec()


def _oss21_apply_page_tools(browser, tab):
    try:
        if not isinstance(tab,BrowserTab): return
        url=tab.view.url().toString()
        if not is_web_url(url): return
        s=browser.data.setdefault("settings",{})
        host=(urlparse(url).hostname or "").lower()
        css=browser.data.get("site_css",{}).get(host,"")
        code="(()=>{document.getElementById('__oss21_custom_css')?.remove();" + ("let s=document.createElement('style');s.id='__oss21_custom_css';s.textContent="+json.dumps(css)+";document.documentElement.appendChild(s);" if css else "") + "})()"
        tab.view.page().runJavaScript(code)
        # Only re-inject toggles if their enabled state needs to be present.
        if s.get("oss21_link_preview"): _oss21_inject_link_preview(tab.view)
        else: tab.view.page().runJavaScript("window.__oss21_link_cleanup?.();document.getElementById('__oss21_link_tip')?.remove();window.__oss21_link_preview=false")
        if s.get("oss21_mouse_gestures"): _oss21_inject_gestures(tab.view)
        else: tab.view.page().runJavaScript("window.__oss21_gesture_remove?.();window.__oss21_gestures=false")
        if s.get("oss21_selection_tools"): _oss21_inject_selection(tab.view,browser)
        else: tab.view.page().runJavaScript("window.__oss21_sel_cleanup?.();document.getElementById('__oss21_selbar')?.remove();window.__oss21_seltools=false")
    except Exception: pass


def _oss21_inject_link_preview(view):
    view.page().runJavaScript(r"""(()=>{if(window.__oss21_link_preview)return;window.__oss21_link_preview=1;let tip=document.createElement('div');tip.id='__oss21_link_tip';tip.style.cssText='display:none;white-space:pre-wrap;position:fixed;z-index:2147483647;max-width:420px;background:#111827;color:#fff;border:1px solid #64748b;border-radius:9px;padding:9px 12px;font:12px Segoe UI;pointer-events:none';document.documentElement.appendChild(tip);const over=e=>{let a=e.target.closest?.('a[href]');if(!a)return;tip.textContent=(a.innerText||a.title||'Bağlantı').trim().slice(0,120)+'\n'+a.href;tip.style.display='block';tip.style.left=Math.max(8,Math.min(innerWidth-430,e.clientX+12))+'px';tip.style.top=Math.max(8,Math.min(innerHeight-80,e.clientY+12))+'px'};const out=e=>{if(e.target.closest?.('a[href]'))tip.style.display='none'};document.addEventListener('mouseover',over,true);document.addEventListener('mouseout',out,true);window.__oss21_link_cleanup=()=>{document.removeEventListener('mouseover',over,true);document.removeEventListener('mouseout',out,true);tip.remove();window.__oss21_link_preview=false}})();""")

def _oss21_inject_gestures(view):
    view.page().runJavaScript(r"""(()=>{if(window.__oss21_gestures)return;window.__oss21_gestures=true;let sx=0,sy=0,active=false;const down=e=>{if(e.button===2){sx=e.clientX;sy=e.clientY;active=true}},up=e=>{if(!active)return;active=false;let dx=e.clientX-sx,dy=e.clientY-sy;if(Math.abs(dx)<55&&Math.abs(dy)<55)return;if(Math.abs(dx)>Math.abs(dy)){if(dx>0)history.back();else history.forward()}else if(dy<0)scrollTo({top:0,behavior:'smooth'});else scrollTo({top:document.documentElement.scrollHeight,behavior:'smooth'})};const ctx=e=>{if(active)e.preventDefault()};document.addEventListener('mousedown',down,true);document.addEventListener('mouseup',up,true);document.addEventListener('contextmenu',ctx,true);window.__oss21_gesture_remove=()=>{document.removeEventListener('mousedown',down,true);document.removeEventListener('mouseup',up,true);document.removeEventListener('contextmenu',ctx,true);window.__oss21_gestures=false}})();""")


def _oss21_inject_selection(view,browser):
    engine=browser.data.get("settings",{}).get("search_engine","Google")
    tpl=json.dumps(f"https://{NOVA_SEARCH_HOST}{NOVA_SEARCH_PATH}?q={{}}" if engine==NOVA_SEARCH_NAME else (SEARCH_ENGINES.get(engine) or SEARCH_ENGINES.get("Google","https://www.google.com/search?q={}")))
    script=r"""(()=>{if(window.__oss21_seltools)return;window.__oss21_seltools=true;const tpl=__TPL__;let bar=document.createElement('div');bar.id='__oss21_selbar';bar.style.cssText='display:none;position:fixed;z-index:2147483647;background:#111827;border:1px solid #7c5cff;padding:5px;border-radius:9px;font:12px Segoe UI';document.documentElement.appendChild(bar);const act=(name,fn)=>{let b=document.createElement('button');b.textContent=name;b.style.cssText='margin:2px;padding:6px 9px;background:#7c5cff;color:white;border:0;border-radius:5px';b.onclick=fn;bar.appendChild(b)};act('Kopyala',()=>{let t=getSelection()?.toString()||'';let x=document.createElement('textarea');x.value=t;document.body.appendChild(x);x.select();document.execCommand('copy');x.remove();bar.style.display='none'});act('Ara',()=>{let t=getSelection()?.toString()||'';if(t)location.href=tpl.replace('{}',encodeURIComponent(t))});act('Gizle',()=>bar.style.display='none');const handler=e=>setTimeout(()=>{let t=getSelection()?.toString().trim()||'';if(t.length<2||t.length>500){bar.style.display='none';return}bar.style.left=Math.max(8,Math.min(innerWidth-230,e.clientX))+'px';bar.style.top=Math.max(8,Math.min(innerHeight-55,e.clientY+8))+'px';bar.style.display='block'},0);document.addEventListener('mouseup',handler,true);window.__oss21_sel_cleanup=()=>{document.removeEventListener('mouseup',handler,true);bar.remove();window.__oss21_seltools=false}})();""".replace("__TPL__",tpl)
    view.page().runJavaScript(script)


def _oss21_voice(browser): OSS21VoiceDialog(browser).exec()
def _oss21_json(browser): OSS21JSONDialog(browser).exec()
def _oss21_css(browser): _oss21_css_editor(browser)
def _oss21_auto(browser): _oss21_automation(browser)
def _oss21_projects(browser): _oss21_project_boards(browser)
def _oss21_archive(browser): _oss21_archive_page(browser)
def _oss21_clipboard_open(browser): _oss21_clipboard(browser)
def _oss21_notifications_open(browser): _oss21_notifications(browser)
def _oss21_market_open(browser): _oss21_market(browser)
def _oss21_diagnostics_open(browser): _oss21_diagnostics(browser)
def _oss21_beta_open(browser): _oss21_beta(browser)
def _oss21_usage_open(browser): _oss21_usage(browser)
def _oss21_lab_open(browser): _oss21_lab(browser)
def _oss21_lock(browser): _oss21_session_lock(browser)
def _oss21_portable(browser): _oss21_portable_profile(browser)
def _oss21_topics(browser): _oss21_topic_map(browser)
def _oss21_history(browser): _oss21_history_suggest(browser)
def _oss21_docs(browser): _oss21_document_search(browser)
def _oss21_similar(browser): _oss21_similar_sources(browser)
def _oss21_privacy(browser): _oss21_privacy_report(browser)
def _oss21_mobile(browser): _oss21_mobile_view(browser)
def _oss21_speed_open(browser): _oss21_speed(browser)
def _oss21_devtools_open(browser): _oss21_devtools(browser)
def _oss21_profiles(browser): browser.open_profiles()
def _oss21_private(browser): browser.new_tab(private=True)
def _oss21_refresh_nova(browser): _oss21_nova_refresh(browser)
def _oss21_ai(browser): _oss21_feature_ai(browser)
def _oss21_link(browser): _oss21_toggle_link_preview(browser)
def _oss21_gesture(browser): _oss21_toggle_gestures(browser)
def _oss21_selection(browser): _oss21_toggle_selection_tools(browser)


def _oss21_run_feature(browser, key):
    handlers={
        "ai":_oss21_ai,"link_preview":_oss21_link,"voice":_oss21_voice,"gestures":_oss21_gesture,"selection":_oss21_selection,
        "profiles":_oss21_profiles,"private":_oss21_private,"privacy_report":_oss21_privacy,"lock":_oss21_lock,"portable":_oss21_portable,
        "topic_map":_oss21_topics,"history_suggest":_oss21_history,"document_search":_oss21_docs,"similar":_oss21_similar,"nova_refresh":_oss21_refresh_nova,
        "devtools":_oss21_devtools_open,"mobile":_oss21_mobile,"speed":_oss21_speed_open,"json":_oss21_json,"css":_oss21_css,
        "automation":_oss21_auto,"projects":_oss21_projects,"archive":_oss21_archive,"clipboard":_oss21_clipboard_open,"notifications":_oss21_notifications_open,
        "market":_oss21_market_open,"diagnostics":_oss21_diagnostics_open,"beta":_oss21_beta_open,"usage":_oss21_usage_open,"lab":_oss21_lab_open,
    }
    try:
        fn=handlers.get(key)
        if fn: fn(browser)
    except Exception as exc:
        QMessageBox.warning(browser,"OSS 2.1 Araç Hatası",f"Özellik çalıştırılamadı:\n{exc}")


def _oss21_wrap_setup_ui(self):
    _oss21_previous_setup_ui(self)
    try:
        button=getattr(self,"tools_button",None)
        menu=button.menu() if button else None
        if menu is None or getattr(self,"_oss21_menu_added",False): return
        self._oss21_menu_added=True
        menu.addSeparator()
        menu.addAction("OSS 2.1 — 30 Yeni Özellik",lambda: OSS21FeatureCenter(self).exec())
        group=menu.addMenu("OSS 2.1 Hızlı Araçlar")
        for key,title,desc in OSS21_FEATURES:
            group.addAction(title,lambda _checked=False,k=key:_oss21_run_feature(self,k))
    except Exception as exc:
        try: self.statusBar().showMessage("OSS 2.1 menüsü yüklenemedi: "+str(exc),3500)
        except Exception: pass


_oss21_previous_setup_ui = MainWindow.setup_ui
MainWindow.setup_ui = _oss21_wrap_setup_ui


_oss21_previous_page_loaded = MainWindow.page_loaded

def _oss21_page_loaded(self, tab):
    try:
        _oss21_previous_page_loaded(self,tab)
    finally:
        try:
            url=tab.view.url().toString()
            if is_web_url(url):
                settings=self.data.setdefault("settings",{})
                if settings.get("oss21_usage_enabled"):
                    stats=self.data.setdefault("oss21_usage",{})
                    stats["visits"]=int(stats.get("visits",0))+1
                    host=(urlparse(url).hostname or "unknown").lower()
                    domains=stats.setdefault("domains",{})
                    domains[host]=int(domains.get(host,0))+1
                    self.save()
                _oss21_apply_page_tools(self,tab)
        except Exception: pass

MainWindow.page_loaded = _oss21_page_loaded


# Initialise optional clipboard history listener if the user had enabled it.
_oss21_previous_main_init = MainWindow.__init__
def _oss21_init(self,*args,**kwargs):
    _oss21_previous_main_init(self,*args,**kwargs)
    try:
        settings=self.data.setdefault("settings",{})
        if settings.get("clipboard_history_enabled") and not getattr(self,"_oss21_clipboard_connected",False):
            QApplication.clipboard().dataChanged.connect(lambda: _oss21_record_clipboard(self)); self._oss21_clipboard_connected=True
    except Exception: pass
MainWindow.__init__ = _oss21_init



# ============================================================
# OSS Browser 2.2.0 — NOVA hızlı ve kalıcı indeks + 40 araç merkezi
# ============================================================
# Bu katman önceki sürümlerin fonksiyonlarını korur; var olan NOVA DB'sini
# yükseltir, kuyruğu kalıcı yapar ve yeni araçları tek merkezde toplar.

import csv as _oss22_csv
import difflib as _oss22_difflib
import socket as _oss22_socket
import ssl as _oss22_ssl
import xml.etree.ElementTree as _oss22_ET
from datetime import date as _oss22_date, timedelta as _oss22_timedelta

APP_VERSION = "7.0.0"
NOVA_WORKERS = 6
NOVA_MAX_PAGES = 4000
NOVA_MAX_DEPTH = 3
NOVA_PAGE_SIZE = 50
NOVA_FTS5_ENABLED = False

_oss22_base_nova_db_connect = _nova_db_connect
_oss22_base_nova_search_db = _nova_search_db
_oss22_base_nova_start_crawler = _nova_start_crawler
_oss22_base_result_html = _nova_result_html
_oss22_base_home_html = _nova_home_html
_oss22_base_browser_nav = BrowserPage.acceptNavigationRequest
_OSS22_WORKERS = []
_OSS22_FEATURES = [
    ("rss", "RSS ve Haber Okuyucu", "RSS/Atom akışlarını oku ve haber bağlantılarını aç."),
    ("domain", "Alan Adı İnceleyicisi", "DNS adreslerini, HTTPS sertifikasını ve yönlendirme yanıtını göster."),
    ("diff", "Web Sayfası Sürüm Karşılaştırma", "İki HTML/TXT/MD kaydındaki metin farklarını karşılaştır."),
    ("calendar", "İnternet Takvimi", "Yerel etkinlik ve hatırlatıcı kaydı oluştur."),
    ("vocab", "Dil Öğrenme Kartları", "Kelime ve anlamlarını kaydet, kendini test et."),
    ("images", "Görsel Bilgi Paneli", "Açık sayfadaki görsellerin adres, boyut ve alt metinlerini listele."),
    ("export", "Sayfa Belgesi Oluşturucu", "Sayfanın HTML, metin veya Markdown taslağını dışa aktar."),
    ("collections", "Bağlantı Koleksiyonları", "Siteleri konu başlıklarında topla ve dışa aktar."),
    ("home", "Ana Sayfa Düzenleyici", "Mevcut kişiselleştirilebilir ana sayfa ayarlarını aç."),
    ("adaptive", "Uyarlanabilir Arayüz", "Kompakt araç çubuğu ve erişilebilir görünüm seçeneklerini yönet."),
    ("accessibility", "Erişilebilirlik Merkezi", "Yakınlaştırma, yazı boyutu ve kontrast yardımcılarını ayarla."),
    ("sidebar", "Yan Panel Ayarları", "Yer imleri, notlar ve araç panellerini aç."),
    ("present", "Sunum / Odak Modu", "Tarayıcıyı tam ekran moduna al veya geri dön."),
    ("context", "Sağ Tık Araç Tercihleri", "Bağlam menüsü için kişisel eylem tercihlerini kaydet."),
    ("appearance", "Otomatik Görünüm Profili", "Görünüm profilini seç ve yerel olarak sakla."),
    ("restore", "Ayar Geri Alma Yedeği", "Mevcut ayarların geri yükleme yedeğini kaydet."),
    ("syntax", "Gelişmiş NOVA Söz Dizimi", "site:, intitle:, after:, before: ve filetype: kullanımını göster."),
    ("ranking", "Kişisel Sonuç Sıralaması", "Tercih edilen ve dışlanacak alan adlarını belirle."),
    ("language", "Çok Dilli Arama Ayarı", "Türkçe önceliği veya tüm diller arasında geçiş yap."),
    ("quality", "Arama Kalitesi Laboratuvarı", "Örnek bir sorgunun eşleşmelerini ve kaynaklarını test et."),
    ("documents", "Yerel Belge Arama", "Klasördeki TXT/MD/HTML/PDF belgelerde ara."),
    ("maintenance", "NOVA İndeks Bakımı", "Hatalı taramaları yeniden kuyruğa al ve SQLite bakımını yap."),
    ("saved_searches", "Kaydedilmiş Aramalar", "Sık kullandığın sorguları kaydet ve tekrar çalıştır."),
    ("graph", "Kaynak Bağlantı Grafiği", "NOVA indeksinin tuttuğu sayfalar arası bağlantıları incele."),
    ("checksum", "İndirme SHA-256 Doğrulayıcı", "Seçtiğin dosyanın SHA-256 özetini hesapla."),
    ("permissions", "Site İzinleri Denetimi", "Mevcut tarayıcı site izinleri ekranını aç."),
    ("recovery", "Profil ve Oturum Kurtarma", "Mevcut yedekleme/geri yükleme aracını aç."),
    ("storage", "Depolama Alanı Yöneticisi", "OSS Browser klasörlerinin yaklaşık disk kullanımını göster."),
    ("proxy", "Bağlantı Profili Notları", "Proxy yapılandırmasını kaydet ve uygulanma sınırlarını göster."),
    ("update_history", "Güncelleme Geçmişi", "Son sürüm kontrolü ve yerel kanal tercihlerini göster."),
    ("media", "Medya Kütüphanesi", "Yerel medya dosyası ekle veya listeyi aç."),
    ("postprocess", "İndirme Sonrası Araçlar", "İndirilen dosyayı seç, özetini hesapla veya klasörünü aç."),
    ("tables", "Web Tablosu CSV Dışa Aktarma", "Açık sayfadaki HTML tablolarını CSV olarak kaydet."),
    ("print", "Akıllı PDF / Yazdırma", "Açık sayfayı PDF olarak kaydet."),
    ("screenshot", "Sayfa Görüntüsü Kaydet", "Açık sekmenin görünen alanını PNG olarak kaydet."),
    ("preview", "Yerel Dosya Önizleme", "Metin, JSON, CSV, HTML ve görsel dosyalarını önizle."),
    ("sdk", "OSS Araç Geliştirme Kiti", "Örnek eklenti dosyalarıyla bir SDK klasörü oluştur."),
    ("test_lab", "Özellik Test Laboratuvarı", "Kurulum ve NOVA indeks kontrollerini çalıştır."),
    ("rules", "Olay Tabanlı Otomasyon", "Alan adı ziyaret edildiğinde uyarı veya URL açma kuralı ekle."),
    ("channel", "Kararlı / Beta Kanalı", "Güncelleme kanalını ve beta manifest adresini seç."),
]


def _nova_db_connect_v22():
    """Eski SQLite indeksini koruyup FTS5 ve kalıcı tarama kuyruğunu ekle."""
    global NOVA_FTS5_ENABLED
    conn = _oss22_base_nova_db_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS nova_crawl_queue (
        url TEXT PRIMARY KEY, depth INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'discovered',
        added_at INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL DEFAULT 0
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nova_queue_status ON nova_crawl_queue(status, depth, added_at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS nova_links (
        source_url TEXT NOT NULL, target_url TEXT NOT NULL,
        PRIMARY KEY(source_url,target_url)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nova_links_target ON nova_links(target_url)")
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(url UNINDEXED,title,snippet,content,domain UNINDEXED,category UNINDEXED,tokenize='unicode61 remove_diacritics 2')")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS nova_pages_ai AFTER INSERT ON pages BEGIN
            INSERT INTO pages_fts(rowid,url,title,snippet,content,domain,category)
            VALUES(new.id,new.url,new.title,new.snippet,new.content,new.domain,new.category);
        END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS nova_pages_au AFTER UPDATE ON pages BEGIN
            DELETE FROM pages_fts WHERE rowid=old.id;
            INSERT INTO pages_fts(rowid,url,title,snippet,content,domain,category)
            VALUES(new.id,new.url,new.title,new.snippet,new.content,new.domain,new.category);
        END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS nova_pages_ad AFTER DELETE ON pages BEGIN
            DELETE FROM pages_fts WHERE rowid=old.id;
        END""")
        page_count = int(conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0])
        fts_count = int(conn.execute("SELECT COUNT(*) FROM pages_fts").fetchone()[0])
        if page_count != fts_count:
            conn.execute("DELETE FROM pages_fts")
            conn.execute("INSERT INTO pages_fts(rowid,url,title,snippet,content,domain,category) SELECT id,url,title,snippet,content,domain,category FROM pages")
        NOVA_FTS5_ENABLED = True
    except sqlite3.OperationalError:
        # FTS5 bulunmayan Python derlemelerinde arama LIKE yöntemine düşer.
        NOVA_FTS5_ENABLED = False
    conn.commit()
    return conn


_nova_db_connect = _nova_db_connect_v22


def _nova_seed_url(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    url = _nova_normalize_url(raw)
    try:
        parsed = urlparse(url)
        if not parsed.hostname or "." not in parsed.hostname:
            return ""
        if parsed.scheme not in ("http", "https"):
            return ""
        path = parsed.path or "/"
        # Source additions are start URLs, not search/query URLs.
        return parsed._replace(path=path, params="", fragment="").geturl()
    except Exception:
        return ""


def _nova_get_saved_custom_sources(browser):
    urls = []
    try:
        for raw in browser.data.get("nova_custom_sources", []):
            url = _nova_seed_url(raw)
            if url and url not in urls:
                urls.append(url)
    except Exception:
        pass
    return urls


def _nova_roots_from_urls(urls):
    roots = set()
    for url in urls:
        domain = _nova_domain(url)
        if domain:
            roots.add(domain)
    return roots


def _nova_host_allowed(host, roots):
    host = (host or "").lower().removeprefix("www.")
    return any(host == root or host.endswith("." + root) for root in roots if root)


def _nova_safe_crawl_url(raw, roots):
    url = _nova_seed_url(raw)
    if not url:
        return ""
    p = urlparse(url)
    host = _nova_domain(url)
    if not _nova_host_allowed(host, roots):
        return ""
    # Avoid authentication, session and endless query/search URLs.
    blocked_parts = ("/login", "/logout", "/signin", "/signup", "/register", "/cart", "/checkout", "/account", "/wp-admin", "/search")
    if any(part in (p.path or "").lower() for part in blocked_parts):
        return ""
    if p.path.lower().endswith((".zip", ".exe", ".msi", ".7z", ".rar", ".mp4", ".mp3", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".doc", ".docx", ".apk", ".iso")):
        return ""
    # Strip common trackers to reduce duplicate URLs.
    try:
        pairs = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
        pairs = [(k, v) for k, v in pairs if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid", "mc_cid", "mc_eid", "ref_src"}]
        query = urllib.parse.urlencode(pairs[:12], doseq=True)
        return p._replace(query=query, fragment="").geturl()
    except Exception:
        return url


def _nova_queue_add(conn, url, depth=0, source="discovered", requeue=False):
    now = int(time.time())
    if requeue:
        conn.execute("""INSERT INTO nova_crawl_queue(url,depth,status,attempts,last_error,source,added_at,updated_at)
            VALUES(?,?,'pending',0,'',?,?,?) ON CONFLICT(url) DO UPDATE SET depth=excluded.depth,status='pending',attempts=0,last_error='',source=excluded.source,updated_at=excluded.updated_at""",
            (url, depth, source, now, now))
    else:
        conn.execute("""INSERT OR IGNORE INTO nova_crawl_queue(url,depth,status,attempts,last_error,source,added_at,updated_at)
            VALUES(?,?,'pending',0,'',?,?,?)""", (url, depth, source, now, now))


def _nova_crawler_snapshot_v22(self):
    try:
        conn = _nova_db_connect()
        indexed = int(conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0])
        queued = int(conn.execute("SELECT COUNT(*) FROM nova_crawl_queue WHERE status IN ('pending','in_progress')").fetchone()[0])
        failed = int(conn.execute("SELECT COUNT(*) FROM nova_crawl_queue WHERE status='error'").fetchone()[0])
        conn.close()
    except Exception:
        indexed, queued, failed = 0, 0, 0
    with self.lock:
        return {"running": bool(self.running), "pages": int(self.pages), "errors": int(self.errors), "queued": queued, "indexed": indexed, "failed": failed, "workers": int(getattr(self, "worker_count", NOVA_WORKERS)), "fts5": bool(NOVA_FTS5_ENABLED)}


def _nova_crawler_add_seeds_v22(self, seeds, requeue=True):
    prepared = []
    with self.lock:
        current = list(getattr(self, "extra_seeds", []))
        for raw in seeds or []:
            url = _nova_seed_url(raw)
            if url and url not in current and url not in NOVA_SEEDS:
                current.append(url)
            if url and url not in prepared:
                prepared.append(url)
        self.extra_seeds = current
    if prepared:
        try:
            conn = _nova_db_connect()
            roots = _nova_roots_from_urls(list(NOVA_SEEDS) + list(self.extra_seeds))
            for url in prepared:
                safe = _nova_safe_crawl_url(url, roots)
                if safe:
                    _nova_queue_add(conn, safe, 0, "user", requeue=requeue)
            conn.commit()
            conn.close()
        except Exception as exc:
            try: self.errors += 1
            except Exception: pass
    return prepared


def _nova_crawler_start_v22(self, force=False, extra_seeds=None, worker_count=None, session_limit=None):
    with self.lock:
        if self.running:
            already_running = True
        else:
            already_running = False
            self.stop_flag = False
            self.running = True
            self.pages = 0
            self.errors = 0
            self.force_requested = bool(force)
            self.worker_count = max(1, min(12, int(worker_count or getattr(self, "worker_count", NOVA_WORKERS))))
            self.session_limit = max(100, min(20000, int(session_limit or getattr(self, "session_limit", NOVA_MAX_PAGES))))
    if already_running:
        if extra_seeds:
            _nova_crawler_add_seeds_v22(self, extra_seeds, requeue=True)
        return False
    self.extra_seeds = list(getattr(self, "extra_seeds", []))
    _nova_crawler_add_seeds_v22(self, extra_seeds or [], requeue=False)
    self.thread = threading.Thread(target=_nova_crawler_run_v22, args=(self,), daemon=True, name="NOVA-Indexer-v22")
    self.thread.start()
    return True


def _nova_crawler_save_row_v22(self, row):
    conn = _nova_db_connect()
    now = int(time.time())
    conn.execute("""INSERT INTO pages(url,title,snippet,content,domain,category,crawled_at,depth)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET title=excluded.title,snippet=excluded.snippet,content=excluded.content,domain=excluded.domain,category=excluded.category,crawled_at=excluded.crawled_at,depth=excluded.depth""",
        (row["url"], row["title"], row["snippet"], row["content"], row["domain"], row["category"], now, row["depth"]))
    conn.execute("UPDATE nova_crawl_queue SET status='done',last_error='',updated_at=? WHERE url=?", (now, row["url"]))
    for target in row.get("links", []):
        conn.execute("INSERT OR IGNORE INTO nova_links(source_url,target_url) VALUES(?,?)", (row["url"], target))
    conn.commit()
    conn.close()


def _nova_fetch_job_v22(url, depth, roots):
    try:
        safe = _nova_safe_crawl_url(url, roots)
        if not safe:
            return {"url": url, "depth": depth, "row": None, "error": "URL filtreden geçtiği için taranmadı."}
        raw = _nova_fetch_page(safe)
        if not raw:
            return {"url": safe, "depth": depth, "row": None, "error": "HTML yanıtı alınamadı veya kaynak erişime izin vermedi."}
        row = _nova_extract_page(safe, raw)
        row["depth"] = depth
        allowed_links = []
        for link in row.get("links", []):
            candidate = _nova_safe_crawl_url(link, roots)
            if candidate and candidate not in allowed_links:
                allowed_links.append(candidate)
            if len(allowed_links) >= 80:
                break
        row["links"] = allowed_links
        return {"url": safe, "depth": depth, "row": row, "error": ""}
    except Exception as exc:
        return {"url": url, "depth": depth, "row": None, "error": str(exc)[:300]}


def _nova_crawler_run_v22(self):
    scanned = 0
    try:
        roots_urls = list(NOVA_SEEDS) + list(getattr(self, "extra_seeds", []))
        roots = _nova_roots_from_urls(roots_urls)
        conn = _nova_db_connect()
        # Recover a queue interrupted by a previous application close.
        conn.execute("UPDATE nova_crawl_queue SET status='pending',updated_at=? WHERE status='in_progress'", (int(time.time()),))
        for seed in roots_urls:
            url = _nova_safe_crawl_url(seed, roots)
            if url:
                _nova_queue_add(conn, url, 0, "seed" if seed in NOVA_SEEDS else "user", requeue=False)
        now = int(time.time())
        # Refresh entry points older than 12 hours so the same small seed list does not go stale forever.
        stale_before = now - 12 * 3600
        for seed in roots_urls:
            url = _nova_safe_crawl_url(seed, roots)
            if not url: continue
            row = conn.execute("SELECT crawled_at FROM pages WHERE url=?", (url,)).fetchone()
            queued = conn.execute("SELECT status FROM nova_crawl_queue WHERE url=?", (url,)).fetchone()
            if row and int(row[0] or 0) < stale_before and queued and queued[0] == "done":
                conn.execute("UPDATE nova_crawl_queue SET status='pending',last_error='',updated_at=? WHERE url=?", (now, url))
        if bool(getattr(self, "force_requested", False)):
            # Explicit full reindex requests recrawl all indexed URLs and can take longer.
            conn.execute("UPDATE nova_crawl_queue SET status='pending',last_error='',updated_at=? WHERE status IN ('done','error')", (now,))
            self.force_requested = False
        conn.commit(); conn.close()

        worker_count = max(1, min(12, int(getattr(self, "worker_count", NOVA_WORKERS))))
        session_limit = max(100, int(getattr(self, "session_limit", NOVA_MAX_PAGES)))
        while scanned < session_limit:
            with self.lock:
                if self.stop_flag:
                    break
                dynamic_urls = list(getattr(self, "extra_seeds", []))
            roots = _nova_roots_from_urls(list(NOVA_SEEDS) + dynamic_urls)
            conn = _nova_db_connect()
            batch = conn.execute("SELECT url,depth FROM nova_crawl_queue WHERE status='pending' ORDER BY depth ASC, added_at ASC LIMIT ?", (worker_count,)).fetchall()
            if not batch:
                conn.close()
                break
            now = int(time.time())
            for url, depth in batch:
                conn.execute("UPDATE nova_crawl_queue SET status='in_progress',attempts=attempts+1,updated_at=? WHERE url=? AND status='pending'", (now, url))
            conn.commit(); conn.close()
            actual_batch = [(url, int(depth or 0)) for url, depth in batch]
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="NOVA-Fetch") as pool:
                futures = {pool.submit(_nova_fetch_job_v22, url, depth, set(roots)): (url, depth) for url, depth in actual_batch}
                for future in as_completed(futures):
                    url, depth = futures[future]
                    scanned += 1
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {"url": url, "depth": depth, "row": None, "error": str(exc)}
                    row = result.get("row")
                    if row:
                        try:
                            self._save_row(row)
                            self.pages += 1
                            if depth < NOVA_MAX_DEPTH:
                                active_roots = _nova_roots_from_urls(list(NOVA_SEEDS) + list(getattr(self, "extra_seeds", [])))
                                conn = _nova_db_connect()
                                for link in row.get("links", []):
                                    safe = _nova_safe_crawl_url(link, active_roots)
                                    if safe:
                                        _nova_queue_add(conn, safe, depth + 1, "discovered", requeue=False)
                                conn.commit(); conn.close()
                        except Exception as exc:
                            try:
                                err_conn = _nova_db_connect()
                                err_conn.execute("UPDATE nova_crawl_queue SET status='error',last_error=?,updated_at=? WHERE url=?", (str(exc)[:300], int(time.time()), url))
                                err_conn.commit(); err_conn.close()
                            except Exception: pass
                            self.errors += 1
                    else:
                        err = str(result.get("error") or "Kaynak sonuç vermedi.")
                        try:
                            err_conn = _nova_db_connect()
                            err_conn.execute("UPDATE nova_crawl_queue SET status='error',last_error=?,updated_at=? WHERE url=?", (err[:300], int(time.time()), url))
                            err_conn.commit(); err_conn.close()
                        except Exception: pass
                        self.errors += 1
                    try:
                        conn = _nova_db_connect()
                        self.queued = int(conn.execute("SELECT COUNT(*) FROM nova_crawl_queue WHERE status IN ('pending','in_progress')").fetchone()[0])
                        conn.close()
                    except Exception: pass
                    if scanned >= session_limit:
                        with self.lock:
                            self.stop_flag = True
                        break
    except Exception as exc:
        try:
            with self.lock: self.errors += 1
        except Exception: pass
    finally:
        try:
            conn = _nova_db_connect()
            conn.execute("UPDATE nova_crawl_queue SET status='pending',updated_at=? WHERE status='in_progress'", (int(time.time()),))
            conn.commit()
            self.queued = int(conn.execute("SELECT COUNT(*) FROM nova_crawl_queue WHERE status='pending'").fetchone()[0])
            conn.close()
        except Exception: pass
        with self.lock:
            self.running = False
            self.stop_flag = False


_NovaCrawler.start = _nova_crawler_start_v22
_NovaCrawler.snapshot = _nova_crawler_snapshot_v22
_NovaCrawler._save_row = _nova_crawler_save_row_v22
_NovaCrawler.add_seeds = _nova_crawler_add_seeds_v22
_NovaCrawler._run = _nova_crawler_run_v22


def _nova_start_crawler_v22(browser, force=False, extra_seeds=None):
    custom = _nova_get_saved_custom_sources(browser)
    extras = list(custom)
    for raw in (extra_seeds or []):
        url = _nova_seed_url(raw)
        if url and url not in extras: extras.append(url)
    crawler = getattr(browser, "_nova_crawler", None)
    if crawler is None:
        crawler = _NovaCrawler(); browser._nova_crawler = crawler
    settings = browser.data.get("settings", {})
    workers = settings.get("nova_workers", NOVA_WORKERS)
    session_limit = settings.get("nova_session_limit", 4000)
    started = crawler.start(force=force, extra_seeds=extras, worker_count=workers, session_limit=session_limit)
    if started:
        try: browser.statusBar().showMessage("NOVA indeksleme kuyruğa alındı; bulunan yeni sayfalar anında aramaya eklenir.", 3500)
        except Exception: pass
    return started


_nova_start_crawler = _nova_start_crawler_v22


def _nova_search_db_v22(query, page=1, limit=NOVA_PAGE_SIZE, language_filter="turkish_only", category_filter="all", recency_filter="any"):
    query = _nova_clean(query)
    page = max(1, int(page or 1)); limit = max(1, min(100, int(limit or NOVA_PAGE_SIZE)))
    if not query: return [], 0
    site_filter = ""; title_filter = ""; after_date = ""; before_date = ""; filetype = ""
    terms = []
    tokens = re.findall(r'"[^\"]+"|\S+', query)
    for token in tokens:
        low = token.lower()
        if low.startswith("site:"): site_filter = low[5:].strip().removeprefix("www.")
        elif low.startswith("intitle:"): title_filter = token[8:].strip().strip('"')
        elif low.startswith("after:"): after_date = token[6:].strip()
        elif low.startswith("before:"): before_date = token[7:].strip()
        elif low.startswith("filetype:"): filetype = low[9:].strip().lstrip(".")
        else:
            phrase = token.strip('"').lower()
            if phrase: terms.extend(re.findall(r"[\wğüşöçıİĞÜŞÖÇ-]+", phrase, flags=re.UNICODE))
    conn = _nova_db_connect()
    clauses = []; args = []
    if site_filter:
        clauses.append("(p.domain = ? OR p.domain LIKE ?)"); args.extend([site_filter, "%" + "." + site_filter])
    if title_filter:
        clauses.append("p.title LIKE ?"); args.append("%" + title_filter + "%")
    allowed_categories = {"docs", "code", "gaming", "wiki", "news", "web"}
    if category_filter in allowed_categories:
        clauses.append("p.category = ?"); args.append(category_filter)
    if recency_filter == "week": clauses.append("p.crawled_at >= ?"); args.append(int(time.time()) - 7 * 86400)
    elif recency_filter == "month": clauses.append("p.crawled_at >= ?"); args.append(int(time.time()) - 30 * 86400)
    if after_date:
        try: clauses.append("p.crawled_at >= ?"); args.append(int(datetime.strptime(after_date, "%Y-%m-%d").timestamp()))
        except Exception: pass
    if before_date:
        try: clauses.append("p.crawled_at < ?"); args.append(int((datetime.strptime(before_date, "%Y-%m-%d") + _oss22_timedelta(days=1)).timestamp()))
        except Exception: pass
    if filetype:
        clauses.append("lower(p.url) LIKE ?"); args.append("%." + filetype.lower() + "%")
    where = (" AND ".join(clauses) if clauses else "1=1")
    rows = []
    try:
        if terms and NOVA_FTS5_ENABLED:
            fts_tokens = []
            for term in terms[:12]:
                # FTS phrase quoting avoids syntax errors from punctuation and supports prefix matches.
                safe_term = term.replace('"', '""')
                fts_tokens.append('"' + safe_term + '"*')
            fts_query = " AND ".join(fts_tokens)
            sql = "SELECT p.url,p.title,p.snippet,p.content,p.domain,p.category,p.crawled_at FROM pages p JOIN pages_fts ON pages_fts.rowid=p.id WHERE pages_fts MATCH ? AND " + where + " LIMIT 4000"
            rows = conn.execute(sql, [fts_query] + args).fetchall()
        else:
            fallback_clauses = list(clauses); fallback_args = list(args)
            for term in terms[:8]:
                like = "%" + term + "%"
                fallback_clauses.append("(p.title LIKE ? OR p.url LIKE ? OR p.snippet LIKE ? OR p.content LIKE ?)")
                fallback_args.extend([like, like, like, like])
            sql = "SELECT p.url,p.title,p.snippet,p.content,p.domain,p.category,p.crawled_at FROM pages p WHERE " + (" AND ".join(fallback_clauses) if fallback_clauses else "1=1") + " LIMIT 5000"
            rows = conn.execute(sql, fallback_args).fetchall()
    except sqlite3.OperationalError:
        # If an older SQLite doesn't provide FTS5 or its index needs repair, fall back to LIKE.
        fallback_clauses = list(clauses); fallback_args = list(args)
        for term in terms[:8]:
            like = "%" + term + "%"; fallback_clauses.append("(p.title LIKE ? OR p.url LIKE ? OR p.snippet LIKE ? OR p.content LIKE ?)"); fallback_args.extend([like, like, like, like])
        try: rows = conn.execute("SELECT p.url,p.title,p.snippet,p.content,p.domain,p.category,p.crawled_at FROM pages p WHERE " + (" AND ".join(fallback_clauses) if fallback_clauses else "1=1") + " LIMIT 5000", fallback_args).fetchall()
        except Exception: rows = []
    conn.close()
    mode = language_filter if language_filter in ("all", "turkish_first", "turkish_only") else "turkish_only"
    preferred = set(); excluded = set()
    try:
        # Personal ranking settings are set by the 40-tools dialog through module-level caches.
        preferred = set(_OSS22_PREFERRED_DOMAINS)
        excluded = set(_OSS22_EXCLUDED_DOMAINS)
    except Exception: pass
    scored = []
    for url, title, snippet, content, domain, category, crawled_at in rows:
        title = title or domain; snippet = snippet or (content or "")[:320]
        item = {"url": url, "title": title, "snippet": snippet, "content": content or "", "domain": domain, "category": category, "crawled_at": crawled_at}
        is_turkish = _nova_is_turkish_source(item)
        if mode == "turkish_only" and not is_turkish: continue
        domain_norm = str(domain or _nova_domain(url)).lower().removeprefix("www.")
        if domain_norm in excluded or any(domain_norm.endswith("." + x) for x in excluded): continue
        title_l = str(title).lower(); url_l = str(url).lower(); snippet_l = str(snippet).lower(); content_l = str(content or "").lower()
        score = 0
        for term in terms:
            if term in title_l: score += 26
            if title_l.startswith(term): score += 10
            if term in url_l: score += 7
            if term in snippet_l: score += 5
            if term in content_l: score += 1
        if terms:
            phrase = " ".join(terms).strip()
            if phrase and phrase in (title_l + " " + snippet_l): score += 18
        if site_filter and (domain_norm == site_filter or domain_norm.endswith("." + site_filter)): score += 12
        if title_filter and title_filter.lower() in title_l: score += 20
        if domain_norm in preferred or any(domain_norm.endswith("." + x) for x in preferred): score += 35
        score += min(6, int((int(crawled_at or 0) / 86400) % 7)) if crawled_at else 0
        item["score"] = score; item["is_turkish"] = is_turkish
        scored.append(item)
    if mode == "turkish_first": scored.sort(key=lambda i: (bool(i["is_turkish"]), i["score"], int(i.get("crawled_at") or 0)), reverse=True)
    else: scored.sort(key=lambda i: (i["score"], int(i.get("crawled_at") or 0)), reverse=True)
    total = len(scored); start = (page - 1) * limit
    result = [{k: v for k, v in it.items() if k not in ("content", "score", "is_turkish", "crawled_at")} for it in scored[start:start + limit]]
    return result, total


_nova_search_db = _nova_search_db_v22
_OSS22_PREFERRED_DOMAINS = set()
_OSS22_EXCLUDED_DOMAINS = set()


def _nova_result_html_v22(browser, query, results, total, page):
    output = _oss22_base_result_html(browser, query, results, total, page)
    snap = _nova_status_snapshot(browser)
    notice = f'''<div class="nova-v22-status"><span><b>NOVA dizini:</b> {int(snap.get('indexed',0)):,} sayfa</span><span><b>Kuyruk:</b> {int(snap.get('queued',0)):,}</span><span><b>Hatalı:</b> {int(snap.get('failed',0)):,}</span><a href="https://{NOVA_SEARCH_HOST}/admin">Dizin yönetimi</a><a href="https://{NOVA_SEARCH_HOST}/reindex">Tam yeniden tara</a></div>'''
    css = ".nova-v22-status{display:flex;flex-wrap:wrap;align-items:center;gap:10px;background:#101a2a;border:1px solid #263752;border-radius:12px;padding:10px 12px;margin:12px 0 18px;color:#aab9cf;font:12px Segoe UI}.nova-v22-status a{color:#b9a9ff;text-decoration:none}.nova-v22-status a:hover{text-decoration:underline}"
    if "</style>" in output: output = output.replace("</style>", css + "</style>", 1)
    if "</form>" in output: output = output.replace("</form>", "</form>" + notice, 1)
    if not results and int(total or 0) == 0:
        try:
            settings = browser.data.get("settings", {})
            if settings.get("nova_language_filter", "turkish_only") == "turkish_only":
                other, other_total = _nova_search_db(query, 1, NOVA_PAGE_SIZE, "all", settings.get("nova_category_filter", "all"), settings.get("nova_recency_filter", "any"))
                if other_total:
                    output = output.replace("Bu aramada sonuç yok.", "Dil filtresi eşleşen sonuçları gizledi.")
                    output = output.replace("NOVA kendi dizinini büyütüyor. Dizin güncelleme bağlantısıyla daha fazla site taratabilirsin.", f"Tüm dillerde {other_total:,} eşleşme bulundu. Ayarlar bölümünde NOVA sonuç dilini 'Tüm diller' yapabilir veya Dizin Yönetimi'nden yeni kaynak ekleyebilirsin.")
                else:
                    output = output.replace("Bu aramada sonuç yok.", "Bu sorguyla eşleşen kayıt bulunamadı.")
                    output = output.replace("NOVA kendi dizinini büyütüyor. Dizin güncelleme bağlantısıyla daha fazla site taratabilirsin.", "Dizin yönetiminden alan adı ekleyip taramayı başlat; bulunan sayfalar kaydedildiği anda aramalarda görünür.")
        except Exception: pass
    return output


_nova_result_html = _nova_result_html_v22

# Keep already-open NOVA result pages synchronized with the growing SQLite index.
_oss22_base_nova_search = _nova_search

def _nova_search_v22(browser, query, page=1):
    q = _nova_clean(query)
    direct = _nova_resolve_direct_site(q) if q else None
    result = _oss22_base_nova_search(browser, query, page)
    if q and not direct:
        try:
            tab = browser.current_tab()
            if isinstance(tab, BrowserTab):
                tab._nova_live_query = q
                tab._nova_live_page = max(1, int(page or 1))
                snap = _nova_status_snapshot(browser)
                tab._nova_live_seen_indexed = int(snap.get("indexed", 0))
                tab._nova_live_last_refresh = time.time()
        except Exception: pass
    return result


def _nova_status_update_v22(browser):
    try:
        _nova_status_update_base_v22(browser)
    except Exception: pass
    try:
        tab = browser.current_tab()
        if not isinstance(tab, BrowserTab): return
        query = getattr(tab, "_nova_live_query", "")
        if not query: return
        now = time.time()
        if now - float(getattr(tab, "_nova_live_last_refresh", 0)) < 3.0: return
        snap = _nova_status_snapshot(browser)
        indexed = int(snap.get("indexed", 0))
        if indexed != int(getattr(tab, "_nova_live_seen_indexed", -1)):
            tab._nova_live_last_refresh = now
            _nova_search_v22(browser, query, getattr(tab, "_nova_live_page", 1))
    except Exception: pass


def _nova_home_html_v22(engine_name="NOVA Search", shortcuts=None, browser=None):
    output = _oss22_base_home_html(engine_name, shortcuts, browser)
    link = '<a class="text-link" style="margin-left:12px" href="https://' + NOVA_SEARCH_HOST + '/admin">⚙ Dizin Yönetimi</a>'
    output = output.replace('↻ NOVA dizinini güncelle</a>', '↻ NOVA dizinini güncelle</a>' + link)
    return output


_nova_home_html = _nova_home_html_v22


def _nova_nav_v22(self, url, nav_type, is_main_frame):
    try:
        if is_main_frame and (url.host() or "").lower() == NOVA_SEARCH_HOST and (url.path() or "").rstrip("/") in ("/admin", "/manage"):
            browser = self.browser
            QTimer.singleShot(0, lambda b=browser: OSSNovaAdminDialog(b).exec())
            return False
    except Exception: pass
    return _oss22_base_browser_nav(self, url, nav_type, is_main_frame)


BrowserPage.acceptNavigationRequest = _nova_nav_v22


def _nova_index_add_live_v22(browser, url):
    url = _nova_seed_url(url)
    if not url: return False
    crawler = getattr(browser, "_nova_crawler", None)
    if crawler is None:
        crawler = _NovaCrawler(); browser._nova_crawler = crawler
    if hasattr(crawler, "add_seeds"):
        crawler.add_seeds([url], requeue=True)
    else:
        _nova_queue_add(_nova_db_connect(), url, 0, "user", True)
    if not crawler.running:
        _nova_start_crawler(browser, force=False, extra_seeds=[url])
    return True


class OSSNovaAdminDialogV22(QDialog):
    """Kaynak ekleme, canlı kuyruk, hatalar ve indeks hızını kontrol eden panel."""
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("NOVA Search — Hızlı Dizin Yönetimi")
        self.resize(980, 700)
        self.setStyleSheet("QDialog{background:#0b1019;color:#edf2fa} QLabel{color:#dce5f3} QLineEdit,QComboBox,QListWidget,QTableWidget{background:#111a28;color:#edf2fa;border:1px solid #293850;border-radius:7px;padding:7px} QPushButton{background:#242044;color:#f7f5ff;border:1px solid #554b8b;border-radius:8px;padding:8px 12px} QPushButton:hover{background:#393164} QTabWidget::pane{border:1px solid #293850;border-radius:8px}")
        root = QVBoxLayout(self)
        title = QLabel("NOVA SEARCH / INDEX CONTROL")
        title.setStyleSheet("font-size:20px;font-weight:900;color:#a99aff")
        root.addWidget(title)
        root.addWidget(QLabel("Kaynak ekleyince tarama hemen kuyruğa alınır. Her başarılı sayfa kaydedildiği anda FTS arama indeksine girer; uygulamayı yeniden başlatmak kuyruğu silmez."))
        self.stats = QLabel("İndeks durumu alınıyor…"); self.stats.setStyleSheet("background:#111a28;border-radius:10px;padding:12px;font-weight:650")
        root.addWidget(self.stats)
        bar = QHBoxLayout()
        self.source = QLineEdit(); self.source.setPlaceholderText("Kaynak URL/alan adı · ör. https://docs.python.org/3/ veya site.com")
        add = QPushButton("Kaydet ve hemen tara"); add.clicked.connect(self.add_source)
        bar.addWidget(self.source, 1); bar.addWidget(add); root.addLayout(bar)
        opts = QHBoxLayout()
        opts.addWidget(QLabel("Eşzamanlı bağlantı:"))
        self.workers = QComboBox()
        for n in (2, 4, 6, 8, 10): self.workers.addItem(f"{n} işçi", n)
        cur = int(browser.data.get("settings", {}).get("nova_workers", 6)); ix = self.workers.findData(cur); self.workers.setCurrentIndex(ix if ix >= 0 else 2)
        opts.addWidget(self.workers)
        opts.addWidget(QLabel("Oturum limiti:"))
        self.limit = QComboBox()
        for n in (250, 1000, 2500, 4000, 8000): self.limit.addItem(f"{n:,} sayfa", n)
        cur_limit = int(browser.data.get("settings", {}).get("nova_session_limit", 4000)); ix = self.limit.findData(cur_limit); self.limit.setCurrentIndex(ix if ix >= 0 else 3)
        opts.addWidget(self.limit)
        save_opts = QPushButton("Hız ayarlarını kaydet"); save_opts.clicked.connect(self.save_options); opts.addWidget(save_opts); opts.addStretch(1)
        root.addLayout(opts)
        self.tabs = QTabWidget(); root.addWidget(self.tabs, 1)
        source_page = QWidget(); source_layout = QVBoxLayout(source_page)
        self.sources = QListWidget(); source_layout.addWidget(self.sources, 1)
        source_row = QHBoxLayout(); remove = QPushButton("Seçili özel kaynağı kaldır"); remove.clicked.connect(self.remove_source); source_row.addWidget(remove)
        show_pages = QPushButton("Son indekslenen sayfaları göster"); show_pages.clicked.connect(self.show_latest); source_row.addWidget(show_pages); source_layout.addLayout(source_row)
        self.tabs.addTab(source_page, "Kaynaklar")
        queue_page = QWidget(); queue_layout = QVBoxLayout(queue_page)
        self.queue_table = QTableWidget(0, 4); self.queue_table.setHorizontalHeaderLabels(["Durum", "URL", "Deneme", "Son hata"]); self.queue_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.queue_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); queue_layout.addWidget(self.queue_table, 1)
        queue_row = QHBoxLayout(); retry = QPushButton("Hatalı kayıtları tekrar kuyruğa al"); retry.clicked.connect(self.retry_errors); queue_row.addWidget(retry); vacuum = QPushButton("SQLite indeks bakımını yap"); vacuum.clicked.connect(self.vacuum); queue_row.addWidget(vacuum); queue_layout.addLayout(queue_row)
        self.tabs.addTab(queue_page, "Kuyruk ve Hatalar")
        pages_page = QWidget(); pages_layout = QVBoxLayout(pages_page)
        self.page_filter = QLineEdit(); self.page_filter.setPlaceholderText("İndekste URL/başlık ara…"); pages_layout.addWidget(self.page_filter)
        self.page_table = QTableWidget(0, 3); self.page_table.setHorizontalHeaderLabels(["Başlık", "Alan adı", "URL"]); self.page_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.page_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); pages_layout.addWidget(self.page_table, 1)
        search_rows = QPushButton("İndeks kayıtlarını ara"); search_rows.clicked.connect(self.show_latest); pages_layout.addWidget(search_rows)
        self.tabs.addTab(pages_page, "İndeks Kayıtları")
        buttons = QHBoxLayout()
        start = QPushButton("Devam et / yeni kaynakları tara"); start.clicked.connect(self.start_incremental); buttons.addWidget(start)
        full = QPushButton("Tam yeniden indeksle (daha uzun)"); full.clicked.connect(self.start_full); buttons.addWidget(full)
        stop = QPushButton("Taramayı durdur"); stop.clicked.connect(self.stop_crawl); buttons.addWidget(stop)
        close = QPushButton("Kapat"); close.clicked.connect(self.accept); buttons.addWidget(close)
        root.addLayout(buttons)
        self._sources_signature = None
        self._queue_signature = None
        self.timer = QTimer(self); self.timer.setInterval(1200); self.timer.timeout.connect(self.refresh); self.timer.start()
        self.refresh()

    def save_options(self):
        settings = self.browser.data.setdefault("settings", {})
        settings["nova_workers"] = int(self.workers.currentData() or 6)
        settings["nova_session_limit"] = int(self.limit.currentData() or 4000)
        self.browser.save()
        self.browser.statusBar().showMessage("NOVA indeksleme hızı kaydedildi; bir sonraki tarama bu ayarları kullanır.", 3000)

    def add_source(self):
        url = _nova_seed_url(self.source.text())
        if not url:
            QMessageBox.warning(self, "NOVA kaynağı", "Geçerli bir http/https alan adı veya sayfa adresi gir.")
            return
        sources = self.browser.data.setdefault("nova_custom_sources", [])
        domain = _nova_domain(url)
        if any(_nova_domain(x) == domain for x in sources):
            answer = QMessageBox.question(self, "Kaynak mevcut", "Bu alan adı zaten listede. Kaynağı yeniden tarama kuyruğuna almak ister misin?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes: return
        else:
            sources.append(url)
        self.browser.save()
        if not _nova_index_add_live_v22(self.browser, url):
            QMessageBox.warning(self, "NOVA", "Kaynak kuyruğa eklenemedi.")
        else:
            self.browser.statusBar().showMessage("Kaynak kuyruğa eklendi. Ağ erişimi olan sayfalar indekslendikçe sonuçlara gelir.", 4000)
        self.source.clear(); self.refresh()

    def remove_source(self):
        item = self.sources.currentItem()
        if not item: return
        url = item.data(Qt.ItemDataRole.UserRole)
        if not url: return
        data = self.browser.data.setdefault("nova_custom_sources", [])
        self.browser.data["nova_custom_sources"] = [x for x in data if _nova_seed_url(x) != url]
        self.browser.save(); self.refresh()
        QMessageBox.information(self, "NOVA", "Kaynak listeden kaldırıldı. Daha önce indekslenmiş sayfalar otomatik silinmedi; gerekirse indeks bakımından temizleyebilirsin.")

    def start_incremental(self):
        self.save_options(); _nova_start_crawler(self.browser, force=False); self.refresh()

    def start_full(self):
        self.save_options()
        if QMessageBox.question(self, "Tam yeniden indeksleme", "İndeks kuyruğundaki tamamlanmış URL'ler de yeniden taranacak. Bu uzun sürebilir. Devam edilsin?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            crawler = getattr(self.browser, "_nova_crawler", None)
            if crawler and crawler.running:
                QMessageBox.information(self, "NOVA", "Tarama zaten çalışıyor; önce durdurup sonra yeniden başlat."); return
            _nova_start_crawler(self.browser, force=True); self.refresh()

    def stop_crawl(self):
        crawler = getattr(self.browser, "_nova_crawler", None)
        if crawler and crawler.running:
            crawler.stop_flag = True; self.browser.statusBar().showMessage("NOVA durdurma isteği aldı; devam eden ağ yanıtları tamamlanınca durur.", 3500)

    def retry_errors(self):
        conn = _nova_db_connect(); conn.execute("UPDATE nova_crawl_queue SET status='pending',last_error='',updated_at=? WHERE status='error'", (int(time.time()),)); count = conn.total_changes; conn.commit(); conn.close()
        QMessageBox.information(self, "NOVA", f"{count:,} kayıt yeniden kuyruğa alındı.")
        _nova_start_crawler(self.browser, force=False); self.refresh()

    def vacuum(self):
        try:
            conn = _nova_db_connect(); conn.execute("PRAGMA optimize"); conn.execute("INSERT INTO pages_fts(pages_fts) VALUES('optimize')" if NOVA_FTS5_ENABLED else "SELECT 1"); conn.commit(); conn.execute("VACUUM"); conn.close()
            QMessageBox.information(self, "NOVA", "SQLite/FTS indeks bakımı tamamlandı.")
        except Exception as exc: QMessageBox.warning(self, "NOVA", f"İndeks bakımı tamamlanamadı:\n{exc}")

    def show_latest(self):
        query = self.page_filter.text().strip()
        conn = _nova_db_connect()
        if query:
            rows = conn.execute("SELECT title,domain,url FROM pages WHERE title LIKE ? OR domain LIKE ? OR url LIKE ? ORDER BY crawled_at DESC LIMIT 300", (f"%{query}%", f"%{query}%", f"%{query}%")).fetchall()
        else:
            rows = conn.execute("SELECT title,domain,url FROM pages ORDER BY crawled_at DESC LIMIT 300").fetchall()
        conn.close(); self.page_table.setRowCount(0)
        for row in rows:
            r = self.page_table.rowCount(); self.page_table.insertRow(r)
            for c, value in enumerate(row): self.page_table.setItem(r, c, QTableWidgetItem(str(value or "")))
        self.tabs.setCurrentIndex(2)

    def refresh(self):
        try:
            snap = _nova_status_snapshot(self.browser)
            state = "TARANIYOR" if snap.get("running") else ("KUYRUK BEKLİYOR" if snap.get("queued") else "HAZIR")
            self.stats.setText(f"{state}   ·   İndeks: {snap.get('indexed',0):,} sayfa   ·   Bu oturumda: {snap.get('pages',0):,}   ·   Kuyruk: {snap.get('queued',0):,}   ·   Hatalı: {snap.get('failed',0):,}   ·   İşçi: {snap.get('workers',NOVA_WORKERS)}   ·   FTS5: {'Açık' if snap.get('fts5') else 'LIKE araması'}")
        except Exception as exc: self.stats.setText("NOVA durumu alınamadı: " + str(exc))
        self.sources.clear()
        try:
            source_items = [(_nova_seed_url(item) or str(item)) for item in self.browser.data.get("nova_custom_sources", [])]
            if source_items != self._sources_signature:
                self._sources_signature = source_items
                self.sources.clear()
                for source in source_items:
                    row = QListWidgetItem(source); row.setData(Qt.ItemDataRole.UserRole, source); self.sources.addItem(row)
        except Exception: pass
        try:
            conn = _nova_db_connect(); qrows = conn.execute("SELECT status,url,attempts,last_error FROM nova_crawl_queue WHERE status IN ('pending','in_progress','error') ORDER BY CASE status WHEN 'error' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, updated_at DESC LIMIT 150").fetchall(); conn.close()
            queue_signature = tuple(tuple(x or "" for x in row) for row in qrows)
            if queue_signature != self._queue_signature:
                self._queue_signature = queue_signature
                self.queue_table.setRowCount(0)
                for rowdata in qrows:
                    r=self.queue_table.rowCount(); self.queue_table.insertRow(r)
                    for c,value in enumerate(rowdata): self.queue_table.setItem(r,c,QTableWidgetItem(str(value or "")))
        except Exception: pass


OSSNovaAdminDialog = OSSNovaAdminDialogV22


def _nova_init_v22(self, *args, **kwargs):
    _nova_base_init_v22(self, *args, **kwargs)
    try:
        _nova_bootstrap_db()
        if not getattr(self, "_nova_crawler", None): self._nova_crawler = _NovaCrawler()
        if not getattr(self, "_nova_status_timer", None):
            self._nova_status_timer = QTimer(self); self._nova_status_timer.setInterval(1000); self._nova_status_timer.timeout.connect(lambda: _nova_status_update(self)); self._nova_status_timer.start()
        _nova_start_crawler(self, force=False)
    except Exception as exc:
        try: self.statusBar().showMessage("NOVA başlatılamadı: " + str(exc), 4000)
        except Exception: pass


_nova_base_init_v22 = MainWindow.__init__
MainWindow.__init__ = _nova_init_v22
MainWindow._nova_search = _nova_search_v22
_nova_status_update_base_v22 = _nova_status_update
_nova_status_update = _nova_status_update_v22


def _nova_is_turkish_source_v22(item):
    domain = _nova_domain(item.get("url", "")) or str(item.get("domain", "")).lower().removeprefix("www.")
    if not domain: return False
    if domain.endswith(".tr") or domain in NOVA_TURKISH_DOMAINS or any(domain.endswith("." + d) for d in NOVA_TURKISH_DOMAINS): return True
    title = str(item.get("title", "")); snippet = str(item.get("snippet", "")); content = str(item.get("content", ""))
    combined = " " + _nova_clean((title + " " + snippet + " " + content[:3000]).lower()) + " "
    hint_hits = sum(1 for hint in NOVA_TURKISH_HINTS if hint in combined)
    turkish_chars = sum(combined.count(ch) for ch in "ğüşöçıİĞÜŞÖÇ")
    if domain in NOVA_KNOWN_FOREIGN_DOMAINS or any(domain.endswith("." + d) for d in NOVA_KNOWN_FOREIGN_DOMAINS):
        return hint_hits >= 3 and turkish_chars >= 2
    return hint_hits >= 2 or turkish_chars >= 4


_nova_is_turkish_source = _nova_is_turkish_source_v22

# --------------------------- 40 feature center ---------------------------

def _oss22_current_view(browser):
    try: return browser.current_view()
    except Exception: return None


def _oss22_notice(browser, title, text):
    box = QDialog(browser); box.setWindowTitle(title); box.resize(760, 520); lay = QVBoxLayout(box)
    text_box = QTextBrowser(); text_box.setOpenExternalLinks(True); text_box.setPlainText(str(text)); lay.addWidget(text_box, 1)
    buttons = QHBoxLayout(); copy = QPushButton("Kopyala"); copy.clicked.connect(lambda: QApplication.clipboard().setText(text_box.toPlainText())); buttons.addWidget(copy)
    save = QPushButton("TXT kaydet");
    def do_save():
        path, _ = QFileDialog.getSaveFileName(box, "Metni kaydet", "OSS_rapor.txt", "Metin (*.txt)")
        if path: Path(path).write_text(text_box.toPlainText(), encoding="utf-8")
    save.clicked.connect(do_save); buttons.addWidget(save); buttons.addStretch(1); close = QPushButton("Kapat"); close.clicked.connect(box.accept); buttons.addWidget(close); lay.addLayout(buttons); box.exec()


def _oss22_store(browser, key, value):
    browser.data[key] = value; browser.save()


def _oss22_url_for_browser(browser):
    view = _oss22_current_view(browser)
    return view.url().toString() if view else ""


def _oss22_rss(browser):
    url, ok = QInputDialog.getText(browser, "RSS / Haber Okuyucu", "RSS veya Atom akış URL'si:", QLineEdit.EchoMode.Normal, "https://")
    if not ok or not url.strip(): return
    try:
        req = urllib.request.Request(url.strip(), headers={"User-Agent":"OSSBrowser/2.2 RSS Reader", "Accept":"application/rss+xml,application/atom+xml,application/xml,text/xml,*/*"})
        with urllib.request.urlopen(req, timeout=10) as resp: raw=resp.read(2_000_000)
        root = _oss22_ET.fromstring(raw); entries=[]
        for item in root.findall(".//item")[:80]:
            entries.append((item.findtext("title") or "Başlıksız", item.findtext("link") or "", item.findtext("description") or ""))
        if not entries:
            ns={"a":"http://www.w3.org/2005/Atom"}
            for item in root.findall(".//a:entry", ns)[:80]:
                link=item.find("a:link", ns); entries.append((item.findtext("a:title", default="Başlıksız", namespaces=ns), link.get("href", "") if link is not None else "", item.findtext("a:summary", default="", namespaces=ns)))
        lines=[f"RSS kaynağı: {url}", f"Kayıt: {len(entries)}", ""]
        for i,(title,link,desc) in enumerate(entries,1): lines.append(f"{i}. {title}\n{link}\n{_nova_clean(desc)[:500]}\n")
        _oss22_notice(browser,"RSS / Haber Okuyucu", "\n".join(lines) if entries else "Akışta RSS/Atom girdisi bulunamadı. URL RSS/Atom akışı olmalı.")
    except Exception as exc: QMessageBox.warning(browser,"RSS okuyucu",f"Akış okunamadı:\n{exc}")


def _oss22_domain(browser):
    domain,ok=QInputDialog.getText(browser,"Alan Adı İnceleyicisi","Alan adı gir:",QLineEdit.EchoMode.Normal,"example.com")
    if not ok or not domain.strip(): return
    host=urlparse(domain if "://" in domain else "https://"+domain).hostname
    if not host: QMessageBox.warning(browser,"Alan adı","Geçerli bir alan adı gir."); return
    lines=[f"Alan adı: {host}",""]
    try: lines.append("DNS adresleri: " + ", ".join(sorted({x[4][0] for x in _oss22_socket.getaddrinfo(host,None)})))
    except Exception as exc: lines.append("DNS hatası: " + str(exc))
    try:
        context=_oss22_ssl.create_default_context()
        with _oss22_socket.create_connection((host,443),timeout=5) as sock:
            with context.wrap_socket(sock,server_hostname=host) as ssock:
                cert=ssock.getpeercert(); lines.append("TLS sürümü: "+str(ssock.version())); lines.append("Sertifika sahibi: "+str(cert.get("subject", ""))); lines.append("Sertifika veren: "+str(cert.get("issuer", ""))); lines.append("Geçerlilik bitişi: "+str(cert.get("notAfter", "")))
    except Exception as exc: lines.append("HTTPS sertifikası okunamadı: " + str(exc))
    _oss22_notice(browser,"Alan Adı İnceleyicisi","\n".join(lines))


def _oss22_page_diff(browser):
    p1,_=QFileDialog.getOpenFileName(browser,"İlk sayfa kaydını seç","","Web/metin (*.html *.htm *.txt *.md);;Tüm dosyalar (*.*)")
    if not p1:return
    p2,_=QFileDialog.getOpenFileName(browser,"İkinci sayfa kaydını seç","","Web/metin (*.html *.htm *.txt *.md);;Tüm dosyalar (*.*)")
    if not p2:return
    try:
        a=Path(p1).read_text(encoding="utf-8",errors="replace").splitlines(); b=Path(p2).read_text(encoding="utf-8",errors="replace").splitlines()
        diff="\n".join(_oss22_difflib.unified_diff(a,b,fromfile=Path(p1).name,tofile=Path(p2).name,lineterm=""))
        _oss22_notice(browser,"Web Sayfası Sürüm Karşılaştırma",diff or "Dosyalar arasında metinsel fark bulunmadı.")
    except Exception as exc: QMessageBox.warning(browser,"Karşılaştırma",str(exc))


def _oss22_calendar(browser):
    events=browser.data.setdefault("oss22_calendar_events",[])
    title,ok=QInputDialog.getText(browser,"İnternet Takvimi","Etkinlik adı:")
    if not ok or not title.strip(): return
    d,ok=QInputDialog.getText(browser,"İnternet Takvimi","Tarih (YYYY-AA-GG):",QLineEdit.EchoMode.Normal,_oss22_date.today().isoformat())
    if not ok:return
    try: _oss22_date.fromisoformat(d.strip())
    except Exception: QMessageBox.warning(browser,"Takvim","Tarihi YYYY-AA-GG biçiminde gir."); return
    events.append({"title":title.strip(),"date":d.strip()}); _oss22_store(browser,"oss22_calendar_events",events)
    _oss22_notice(browser,"İnternet Takvimi", "\n".join(f"{e['date']} — {e['title']}" for e in sorted(events,key=lambda x:x['date'])) or "Kayıt yok.")


def _oss22_vocab(browser):
    cards=browser.data.setdefault("oss22_vocab",[])
    word,ok=QInputDialog.getText(browser,"Dil Öğrenme Kartları","Kelime / ifade:")
    if not ok or not word.strip(): return
    meaning,ok=QInputDialog.getText(browser,"Dil Öğrenme Kartları","Anlamı / açıklaması:")
    if not ok:return
    cards.append({"word":word.strip(),"meaning":meaning.strip()}); _oss22_store(browser,"oss22_vocab",cards)
    chosen,ok=QInputDialog.getItem(browser,"Kelime Kartları","Çalışılacak kelime:",[f"{i+1}. {x['word']}" for i,x in enumerate(cards)],max(0,len(cards)-1),False)
    if ok and chosen:
        idx=int(chosen.split(".",1)[0])-1; _oss22_notice(browser,"Kelime Kartı",cards[idx]["word"]+"\n\nAnlamı: "+cards[idx]["meaning"])


def _oss22_image_inspector(browser):
    view=_oss22_current_view(browser)
    if not view:return
    js="JSON.stringify(Array.from(document.images).map(i=>({alt:i.alt||'',src:i.currentSrc||i.src||'',width:i.naturalWidth||i.width,height:i.naturalHeight||i.height})).slice(0,500))"
    def got(raw):
        try:
            arr=json.loads(raw or "[]"); text="\n\n".join(f"{i+1}. {x.get('alt') or '(alt metni yok)'}\n{x.get('width')}×{x.get('height')}\n{x.get('src')}" for i,x in enumerate(arr)); _oss22_notice(browser,"Görsel Bilgi Paneli",text or "Sayfada görsel bulunamadı.")
        except Exception as exc: QMessageBox.warning(browser,"Görsel paneli",str(exc))
    view.page().runJavaScript(js,got)


def _oss22_export_page(browser):
    view=_oss22_current_view(browser)
    if not view:return
    choices=["HTML", "Metin", "Markdown taslağı"]
    kind,ok=QInputDialog.getItem(browser,"Sayfa Belgesi Oluşturucu","Dışa aktarma türü:",choices,0,False)
    if not ok:return
    ext={"HTML":"html","Metin":"txt","Markdown taslağı":"md"}[kind]
    default=Path.home()/"Downloads"/(re.sub(r"[^a-zA-Z0-9_-]+","_",view.title() or "OSS_Sayfa")[:60]+"."+ext)
    path,_=QFileDialog.getSaveFileName(browser,"Sayfayı kaydet",str(default),f"{kind} (*.{ext})")
    if not path:return
    def done(source):
        try:
            if kind=="HTML": content=source
            else:
                parser=_NovaHTMLParser(_oss22_url_for_browser(browser)); parser.feed(source); text="\n".join(_nova_clean(x) for x in parser.text if _nova_clean(x))
                if kind=="Metin": content=text
                else: content=f"# {view.title()}\n\nKaynak: {_oss22_url_for_browser(browser)}\n\n"+text
            Path(path).write_text(content,encoding="utf-8")
            browser.statusBar().showMessage("Sayfa kaydedildi: "+path,3500)
        except Exception as exc: QMessageBox.warning(browser,"Dışa aktarma",str(exc))
    view.page().toHtml(done)


def _oss22_collections(browser):
    data=browser.data.setdefault("oss22_collections",{})
    name,ok=QInputDialog.getText(browser,"Bağlantı Koleksiyonları","Koleksiyon adı:",QLineEdit.EchoMode.Normal,"Araştırmam")
    if not ok or not name.strip(): return
    url=_oss22_url_for_browser(browser)
    if url and url.startswith(("http://","https://")):
        entries=data.setdefault(name.strip(),[])
        if url not in entries: entries.append(url)
    _oss22_store(browser,"oss22_collections",data)
    _oss22_notice(browser,"Bağlantı Koleksiyonları", "\n".join(f"{k}:\n"+"\n".join(v) for k,v in data.items()) or "Koleksiyon yok.")


def _oss22_home(browser):
    try: OSSHomePersonalizationDialog(browser).exec()
    except Exception as exc: QMessageBox.information(browser,"Ana sayfa",f"Ana sayfa ayarlarını Ayarlar menüsünden açabilirsin.\n{exc}")


def _oss22_adaptive(browser):
    settings=browser.data.setdefault("settings",{}); current=bool(settings.get("compact_toolbar",False))
    val,ok=QInputDialog.getItem(browser,"Uyarlanabilir Arayüz","Araç çubuğu görünümü:",["Normal","Kompakt"],1 if current else 0,False)
    if not ok:return
    settings["compact_toolbar"]=(val=="Kompakt"); browser.save()
    QMessageBox.information(browser,"Uyarlanabilir Arayüz","Tercih kaydedildi. Görünümün tamamına uygulanması için tarayıcıyı yeniden başlat.")


def _oss22_accessibility(browser):
    view=_oss22_current_view(browser)
    options=["Yakınlaştırmayı artır (+10%)","Yakınlaştırmayı azalt (-10%)","Varsayılan yakınlaştırma","Yüksek kontrast stilini aç/kapat"]
    choice,ok=QInputDialog.getItem(browser,"Erişilebilirlik Merkezi","İşlem seç:",options,0,False)
    if not ok:return
    if choice==options[0] and view:view.setZoomFactor(min(3.0,view.zoomFactor()+0.1))
    elif choice==options[1] and view:view.setZoomFactor(max(0.5,view.zoomFactor()-0.1))
    elif choice==options[2] and view:view.setZoomFactor(1.0)
    elif choice==options[3] and view:
        s=browser.data.setdefault("settings",{}); enabled=not s.get("oss22_high_contrast",False);s["oss22_high_contrast"]=enabled;browser.save()
        if enabled:view.page().runJavaScript("document.documentElement.style.filter='contrast(1.25)'")
        else:view.page().runJavaScript("document.documentElement.style.filter=''")


def _oss22_sidebar(browser):
    options=[("Yer imleri",lambda:BookmarkDialog(browser).exec()),("Geçmiş",lambda:HistoryDialog(browser).exec()),("Notlar",lambda:OSSNotesDialog(browser).exec()),("İndirmeler",lambda:DownloadsDialog(browser).exec()),("Çalışma alanları",lambda:OSSWorkspacesDialog(browser).exec())]
    choice,ok=QInputDialog.getItem(browser,"Yan Panel Ayarları","Açılacak panel:",[x[0] for x in options],0,False)
    if ok:
        for label,fn in options:
            if label==choice: fn();break


def _oss22_present(browser):
    if browser.isFullScreen(): browser.showNormal()
    else: browser.showFullScreen()


def _oss22_context(browser):
    options=["Seçili metni NOVA'da ara","Bağlantı önizlemesini aç","Seçim araçlarını aç","Fare hareketlerini aç"]
    current=browser.data.setdefault("oss22_context_actions",[])
    choice,ok=QInputDialog.getItem(browser,"Sağ Tık Araç Tercihleri","Kişisel eylemi değiştir:",options,0,False)
    if not ok:return
    if choice in current: current.remove(choice)
    else: current.append(choice)
    _oss22_store(browser,"oss22_context_actions",current)
    QMessageBox.information(browser,"Sağ tık araçları","Kişisel eylem tercihleri kaydedildi. Araçları OSS 2.1 Özellikler Merkezi'nden etkinleştirebilirsin.")


def _oss22_appearance(browser):
    names=["Koyu", "Açık", "Mor vurgu", "Mavi vurgu"]
    chosen,ok=QInputDialog.getItem(browser,"Görünüm Profili","Profil seç:",names,0,False)
    if not ok:return
    s=browser.data.setdefault("settings",{}); s["oss22_appearance_profile"]=chosen; s["dark_mode"]=chosen=="Koyu"; s["accent"]={"Mor vurgu":"#7c5cff","Mavi vurgu":"#329dff"}.get(chosen,s.get("accent","#7c5cff"));browser.save()
    QMessageBox.information(browser,"Görünüm Profili","Seçim kaydedildi. Tarayıcı temasının tüm bileşenlere uygulanması için gerekirse yeniden başlat.")


def _oss22_restore(browser):
    payload={"created_at":datetime.now().isoformat(timespec="seconds"),"settings":browser.data.get("settings",{}),"bookmarks":browser.data.get("bookmarks",[]),"home_shortcuts":browser.data.get("home_shortcuts",[])}
    path,_=QFileDialog.getSaveFileName(browser,"Ayar geri alma yedeği",str(Path.home()/"Downloads"/"oss_browser_settings_backup.json"),"JSON (*.json)")
    if path: Path(path).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8");QMessageBox.information(browser,"Yedek","Ayar yedeği kaydedildi.")


def _oss22_syntax(browser):
    _oss22_notice(browser,"Gelişmiş NOVA Söz Dizimi","site:python.org kurulum\nintitle:Minecraft modları\nafter:2025-01-01 Windows\nbefore:2026-01-01 Python\nfiletype:pdf robotik\n\nBirden çok normal kelime AND mantığıyla aranır. Tarihler YYYY-AA-GG olmalıdır. NOVA yalnızca yerel indeksindeki içerikleri bulur.")


def _oss22_ranking(browser):
    s=browser.data.setdefault("settings",{})
    preferred=", ".join(s.get("nova_preferred_domains",[])); excluded=", ".join(s.get("nova_excluded_domains",[]))
    pref,ok=QInputDialog.getText(browser,"Kişisel Sonuç Sıralaması","Öne çıkarılacak alan adları (virgülle):",QLineEdit.EchoMode.Normal,preferred)
    if not ok:return
    excl,ok=QInputDialog.getText(browser,"Kişisel Sonuç Sıralaması","Gizlenecek alan adları (virgülle):",QLineEdit.EchoMode.Normal,excluded)
    if not ok:return
    s["nova_preferred_domains"]=[x.strip().lower().removeprefix("www.") for x in pref.split(",") if x.strip()]; s["nova_excluded_domains"]=[x.strip().lower().removeprefix("www.") for x in excl.split(",") if x.strip()];browser.save()
    global _OSS22_PREFERRED_DOMAINS,_OSS22_EXCLUDED_DOMAINS
    _OSS22_PREFERRED_DOMAINS=set(s["nova_preferred_domains"]);_OSS22_EXCLUDED_DOMAINS=set(s["nova_excluded_domains"])
    QMessageBox.information(browser,"Sıralama","Tercihler kaydedildi ve sonraki NOVA aramalarında uygulanacak.")


def _oss22_language(browser):
    s=browser.data.setdefault("settings",{}); options=[("Yalnızca Türkçe/Türkiye kaynakları","turkish_only"),("Türkçe kaynakları önce göster","turkish_first"),("Tüm diller","all")]
    chosen,ok=QInputDialog.getItem(browser,"Çok Dilli Arama","Sonuç dili:",[x[0] for x in options],next((i for i,x in enumerate(options) if x[1]==s.get("nova_language_filter","turkish_only")),0),False)
    if ok:
        s["nova_language_filter"]=next(x[1] for x in options if x[0]==chosen);browser.save();QMessageBox.information(browser,"Dil filtresi","Tercih kaydedildi; sonraki NOVA aramasında uygulanır.")


def _oss22_quality(browser):
    q,ok=QInputDialog.getText(browser,"Arama Kalitesi Laboratuvarı","Test sorgusu:")
    if not ok or not q.strip():return
    rows,total=_nova_search_db(q.strip(),1,20,"all","all","any")
    text=f"Sorgu: {q}\nEşleşme: {total}\nFTS5: {NOVA_FTS5_ENABLED}\n\n"+"\n\n".join(f"{i+1}. {r['title']}\n{r['url']}\n{r['snippet']}" for i,r in enumerate(rows))
    _oss22_notice(browser,"Arama Kalitesi Laboratuvarı",text)


def _oss22_documents(browser):
    _oss21_document_search(browser)


def _oss22_maintenance(browser):
    dlg=OSSNovaAdminDialog(browser);dlg.tabs.setCurrentIndex(1);dlg.exec()


def _oss22_saved_searches(browser):
    s=browser.data.setdefault("oss22_saved_searches",[])
    actions=["Yeni arama kaydet"]+[str(x) for x in s]
    chosen,ok=QInputDialog.getItem(browser,"Kaydedilmiş Aramalar","Sorgu seç:",actions,0,False)
    if not ok:return
    if chosen==actions[0]:
        q,ok=QInputDialog.getText(browser,"Kaydet","Sorgu:")
        if ok and q.strip(): s.append(q.strip());_oss22_store(browser,"oss22_saved_searches",s)
    else:
        q=chosen; engine=browser.data.get("settings",{}).get("search_engine",NOVA_SEARCH_NAME)
        if engine==NOVA_SEARCH_NAME: browser._nova_search(q,1)
        else: browser.new_tab((SEARCH_ENGINES.get(engine) or SEARCH_ENGINES["Google"]).format(quote_plus(q)))


def _oss22_graph(browser):
    conn=_nova_db_connect()
    try:
        total=int(conn.execute("SELECT COUNT(*) FROM nova_links").fetchone()[0]); rows=conn.execute("SELECT source_url,target_url FROM nova_links ORDER BY source_url LIMIT 500").fetchall()
        _oss22_notice(browser,"Kaynak Bağlantı Grafiği",f"Kaydedilmiş bağlantı kenarı: {total:,}\nİlk {len(rows)} ilişki:\n\n"+"\n".join(f"{a}  →  {b}" for a,b in rows))
    except Exception as exc: QMessageBox.warning(browser,"Bağlantı grafiği",str(exc))
    finally: conn.close()


def _oss22_checksum(browser):
    path,_=QFileDialog.getOpenFileName(browser,"SHA-256 hesaplanacak dosyayı seç")
    if not path:return
    try:
        h=hashlib.sha256()
        with open(path,"rb") as f:
            for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
        text=f"Dosya: {path}\nBoyut: {Path(path).stat().st_size:,} bayt\nSHA-256: {h.hexdigest()}"
        _oss22_notice(browser,"SHA-256 Doğrulayıcı",text)
    except Exception as exc: QMessageBox.warning(browser,"SHA-256",str(exc))


def _oss22_permissions(browser):
    try: browser.open_security_center()
    except Exception:
        try: OSSSitePermissionsDialog(browser).exec()
        except Exception as exc: QMessageBox.information(browser,"Site izinleri",str(exc))


def _oss22_recovery(browser):
    try:_v5_open_backup(browser)
    except Exception as exc: QMessageBox.information(browser,"Kurtarma","OSS → Yedekleme ve Geri Yükleme menüsünü kullan.\n"+str(exc))


def _oss22_storage(browser):
    rows=[]
    for p in (APP_DIR,PROFILE_DIR,PROFILE_CACHE_DIR,NOVA_INDEX_DIR,DOWNLOAD_DIR):
        try:
            size=sum(x.stat().st_size for x in p.rglob("*") if x.is_file()) if p.exists() else 0
            rows.append(f"{p}\n{size/1024/1024:.2f} MB")
        except Exception as exc: rows.append(f"{p}\nOkunamadı: {exc}")
    _oss22_notice(browser,"Depolama Alanı Yöneticisi","\n\n".join(rows)+"\n\nKlasör silme işlemi otomatik yapılmadı; profil ve NOVA verilerini silmeden önce yedek al.")


def _oss22_proxy(browser):
    s=browser.data.setdefault("settings",{}); current=s.get("oss22_proxy_profile","")
    val,ok=QInputDialog.getText(browser,"Bağlantı Profili Notları","Proxy URL (örn. http://127.0.0.1:8080), kapatmak için boş:",QLineEdit.EchoMode.Normal,current)
    if ok:
        s["oss22_proxy_profile"]=val.strip();browser.save()
        QMessageBox.information(browser,"Proxy profili","Tercih yerel olarak kaydedildi. QtWebEngine proxy ayarlarının uygulanması Qt/Chromium başlangıç yapılandırmasına bağlıdır; bu değer tek başına aktif bir bağlantı garantisi değildir.")


def _oss22_update_history(browser):
    s=browser.data.setdefault("settings",{}); text=f"Uygulama sürümü: {APP_VERSION}\nGüncelleme adresi: {s.get('update_url','(ayarlanmamış)')}\nKararlı adres: {s.get('stable_update_url','(ayarlanmamış)')}\nBeta adresi: {s.get('beta_update_url','(ayarlanmamış)')}\nKanal: {s.get('update_channel','stable')}\nSon kontrol: {s.get('last_update_check','(kayıt yok)')}"
    _oss22_notice(browser,"Güncelleme Geçmişi",text)


def _oss22_media(browser):
    items=browser.data.setdefault("oss22_media_library",[])
    path,_=QFileDialog.getOpenFileName(browser,"Medya dosyası ekle",str(Path.home()),"Medya (*.mp4 *.mkv *.avi *.mp3 *.wav *.webm *.mov);;Tüm dosyalar (*.*)")
    if path and path not in items: items.append(path);_oss22_store(browser,"oss22_media_library",items)
    if items:
        chosen,ok=QInputDialog.getItem(browser,"Medya Kütüphanesi","Dosya seç:",items,max(0,len(items)-1),False)
        if ok and chosen: QDesktopServices.openUrl(QUrl.fromLocalFile(chosen))


def _oss22_postprocess(browser):
    path,_=QFileDialog.getOpenFileName(browser,"İndirilen dosyayı seç",str(DOWNLOAD_DIR))
    if not path:return
    info=f"Dosya: {path}\nBoyut: {Path(path).stat().st_size:,} bayt"
    if QMessageBox.question(browser,"İndirme Sonrası Araçlar",info+"\n\nSHA-256 hesaplayıp gösterilsin mi?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
        h=hashlib.sha256()
        with open(path,"rb") as f:
            for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
        _oss22_notice(browser,"Dosya özeti",info+"\nSHA-256: "+h.hexdigest())
    else: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))


def _oss22_tables(browser):
    view=_oss22_current_view(browser)
    if not view:return
    js="JSON.stringify(Array.from(document.querySelectorAll('table')).map(t=>Array.from(t.querySelectorAll('tr')).map(r=>Array.from(r.querySelectorAll('th,td')).map(c=>(c.innerText||'').replace(/\\s+/g,' ').trim()))))"
    def got(raw):
        try:
            tables=json.loads(raw or "[]")
            if not tables: QMessageBox.information(browser,"Tablo çıkarma","Sayfada HTML tablosu bulunamadı.");return
            names=[f"Tablo {i+1} ({len(t)} satır)" for i,t in enumerate(tables)]
            chosen,ok=QInputDialog.getItem(browser,"Tablo çıkarma","Dışa aktarılacak tablo:",names,0,False)
            if not ok:return
            idx=names.index(chosen); path,_=QFileDialog.getSaveFileName(browser,"CSV kaydet",str(Path.home()/"Downloads"/f"oss_tablo_{idx+1}.csv"),"CSV (*.csv)")
            if not path:return
            with open(path,"w",newline="",encoding="utf-8-sig") as f: _oss22_csv.writer(f).writerows(tables[idx])
            QMessageBox.information(browser,"Tablo çıkarma",f"CSV kaydedildi:\n{path}")
        except Exception as exc: QMessageBox.warning(browser,"Tablo çıkarma",str(exc))
    view.page().runJavaScript(js,got)


def _oss22_print(browser):
    view=_oss22_current_view(browser)
    if not view:return
    path,_=QFileDialog.getSaveFileName(browser,"Sayfayı PDF olarak kaydet",str(Path.home()/"Downloads"/"oss_sayfa.pdf"),"PDF (*.pdf)")
    if not path:return
    try:
        view.page().printToPdf(path)
        browser.statusBar().showMessage("PDF oluşturma başlatıldı: "+path,3500)
    except Exception as exc: QMessageBox.warning(browser,"PDF",str(exc))


def _oss22_screenshot(browser):
    view=_oss22_current_view(browser)
    if not view:return
    path,_=QFileDialog.getSaveFileName(browser,"Görünen alanı PNG olarak kaydet",str(Path.home()/"Pictures"/"oss_screenshot.png"),"PNG (*.png)")
    if path:
        try:
            if view.grab().save(path):QMessageBox.information(browser,"Ekran görüntüsü","Kaydedildi:\n"+path)
            else:QMessageBox.warning(browser,"Ekran görüntüsü","Görüntü kaydedilemedi.")
        except Exception as exc:QMessageBox.warning(browser,"Ekran görüntüsü",str(exc))


def _oss22_preview(browser):
    path,_=QFileDialog.getOpenFileName(browser,"Önizlenecek dosyayı seç",str(Path.home()),"Desteklenen (*.txt *.md *.json *.csv *.html *.htm *.xml *.log *.png *.jpg *.jpeg *.webp *.svg);;Tüm dosyalar (*.*)")
    if not path:return
    p=Path(path)
    if p.suffix.lower() in (".png",".jpg",".jpeg",".webp",".svg"):
        html_text=f"Dosya: {html.escape(str(p))}\nBoyut: {p.stat().st_size:,} bayt"
        _oss22_notice(browser,"Dosya Önizleme",html_text); return
    try:
        text=p.read_text(encoding="utf-8",errors="replace")
        if p.suffix.lower()==".json": text=json.dumps(json.loads(text),ensure_ascii=False,indent=2)
        _oss22_notice(browser,"Dosya Önizleme — "+p.name,text[:2_000_000])
    except Exception as exc: QMessageBox.warning(browser,"Önizleme",str(exc))


def _oss22_sdk(browser):
    folder=QFileDialog.getExistingDirectory(browser,"OSS SDK klasörünü seç",str(Path.home()/"Desktop"))
    if not folder:return
    dest=Path(folder)/"oss_browser_plugin_template"
    try:
        dest.mkdir(parents=True,exist_ok=True)
        (dest/"manifest.json").write_text(json.dumps({"name":"OSS örnek eklenti","version":"1.0.0","entry":"plugin.py","permissions":[]},ensure_ascii=False,indent=2),encoding="utf-8")
        (dest/"plugin.py").write_text('"""OSS Browser örnek eklenti taslağı. Çalıştırmadan önce API sözleşmesini kontrol edin."""\n\nPLUGIN_NAME = "Örnek Araç"\n\ndef register(api):\n    # api.add_action("Örnek işlem", callback)\n    pass\n',encoding="utf-8")
        (dest/"README.md").write_text("# OSS Browser eklenti taslağı\n\nBu dosyalar örnek geliştirme iskeletidir; mevcut tarayıcıya otomatik olarak yüklenmez. Eklenti API'si tanımlanıp izinler eklenmeden çalıştırmayın.\n",encoding="utf-8")
        QMessageBox.information(browser,"OSS SDK","Örnek taslak oluşturuldu:\n"+str(dest))
    except Exception as exc: QMessageBox.warning(browser,"OSS SDK",str(exc))


def _oss22_test_lab(browser):
    lines=[f"OSS Browser {APP_VERSION}",f"SQLite FTS5: {NOVA_FTS5_ENABLED}"]
    try:
        conn=_nova_db_connect(); lines.append("Indexed pages: "+str(conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]));lines.append("Pending queue: "+str(conn.execute("SELECT COUNT(*) FROM nova_crawl_queue WHERE status='pending'").fetchone()[0]));lines.append("Failed queue: "+str(conn.execute("SELECT COUNT(*) FROM nova_crawl_queue WHERE status='error'").fetchone()[0])); lines.append("Stored graph edges: "+str(conn.execute("SELECT COUNT(*) FROM nova_links").fetchone()[0]));conn.close()
    except Exception as exc: lines.append("NOVA DB error: "+str(exc))
    lines.append("QtWebEngine: loaded by application import")
    lines.append("Current URL: "+_oss22_url_for_browser(browser))
    _oss22_notice(browser,"Özellik Test Laboratuvarı","\n".join(lines))


def _oss22_rules(browser):
    rules=browser.data.setdefault("oss22_event_rules",[])
    domain,ok=QInputDialog.getText(browser,"Olay Tabanlı Otomasyon","Sayfa açıldığında uyarılacak alan adı (örn. example.com):")
    if not ok or not domain.strip():return
    action,ok=QInputDialog.getItem(browser,"Olay Tabanlı Otomasyon","Kural:",["Durum çubuğunda uyar","Alan adını ziyaret edince yeni sekmede URL aç"],0,False)
    if not ok:return
    target=""
    if action.startswith("Alan adını"):
        target,ok=QInputDialog.getText(browser,"Otomasyon URL","Açılacak http/https URL:")
        if not ok or not target.startswith(("http://","https://")):return
    rules.append({"domain":domain.strip().lower().removeprefix("www."),"action":"open_url" if target else "notify","target":target,"enabled":True})
    _oss22_store(browser,"oss22_event_rules",rules)
    QMessageBox.information(browser,"Otomasyon","Kural kaydedildi. Alan adına gitme sırasında tetiklenir.")


def _oss22_channel(browser):
    s=browser.data.setdefault("settings",{})
    channel,ok=QInputDialog.getItem(browser,"Güncelleme Kanalı","Kanal:",["Kararlı (stable)","Beta (beta)"],0 if s.get("update_channel","stable")=="stable" else 1,False)
    if not ok:return
    s["update_channel"]="stable" if channel.startswith("Kararlı") else "beta"
    if s["update_channel"]=="beta":
        beta,ok=QInputDialog.getText(browser,"Beta Manifest","Beta latest.json HTTPS adresi:",QLineEdit.EchoMode.Normal,s.get("beta_update_url",""))
        if ok:s["beta_update_url"]=beta.strip()
    browser.save();QMessageBox.information(browser,"Güncelleme Kanalı",f"Kanal tercihi kaydedildi: {s['update_channel']}. Bu ayar beta adresini kaydetmeye yarar; ayrı beta dağıtımı için gerçek bir manifest yayımlanmalıdır.")


def _oss22_dispatch(browser,key):
    handlers={
        "rss":_oss22_rss,"domain":_oss22_domain,"diff":_oss22_page_diff,"calendar":_oss22_calendar,"vocab":_oss22_vocab,"images":_oss22_image_inspector,"export":_oss22_export_page,"collections":_oss22_collections,"home":_oss22_home,"adaptive":_oss22_adaptive,"accessibility":_oss22_accessibility,"sidebar":_oss22_sidebar,"present":_oss22_present,"context":_oss22_context,"appearance":_oss22_appearance,"restore":_oss22_restore,"syntax":_oss22_syntax,"ranking":_oss22_ranking,"language":_oss22_language,"quality":_oss22_quality,"documents":_oss22_documents,"maintenance":_oss22_maintenance,"saved_searches":_oss22_saved_searches,"graph":_oss22_graph,"checksum":_oss22_checksum,"permissions":_oss22_permissions,"recovery":_oss22_recovery,"storage":_oss22_storage,"proxy":_oss22_proxy,"update_history":_oss22_update_history,"media":_oss22_media,"postprocess":_oss22_postprocess,"tables":_oss22_tables,"print":_oss22_print,"screenshot":_oss22_screenshot,"preview":_oss22_preview,"sdk":_oss22_sdk,"test_lab":_oss22_test_lab,"rules":_oss22_rules,"channel":_oss22_channel,
    }
    fn=handlers.get(key)
    if fn:
        try: fn(browser)
        except Exception as exc: QMessageBox.warning(browser,"OSS 2.2 aracı",f"İşlem tamamlanamadı:\n{exc}")


class OSS22FeatureCenter(QDialog):
    def __init__(self,browser):
        super().__init__(browser);self.browser=browser
        self.setWindowTitle("NOVAOS V7 — 50 İşlevsel Araç");self.resize(900,700)
        self.setStyleSheet("QDialog{background:#0b1019;color:#edf2fa} QLabel{color:#dce5f3} QLineEdit,QListWidget{background:#111a28;color:#edf2fa;border:1px solid #293850;border-radius:7px;padding:8px} QPushButton{background:#282147;color:#f7f5ff;border:1px solid #554b8b;border-radius:8px;padding:9px 12px} QPushButton:hover{background:#393164}")
        root=QVBoxLayout(self);head=QLabel("NOVAOS V7 / ARAÇ MERKEZİ");head.setStyleSheet("font-size:21px;font-weight:900;color:#ac9cff");root.addWidget(head)
        root.addWidget(QLabel("50 işlevsel araç: internet, NOVA, güvenlik, dosyalar, geliştirici ve otomasyon. Destek gerektiren özellikler uyarı verir."))
        self.search=QLineEdit();self.search.setPlaceholderText("Araç ara… RSS, alan adı, NOVA, PDF, otomasyon…");root.addWidget(self.search)
        self.list=QListWidget();root.addWidget(self.list,1)
        row=QHBoxLayout();go=QPushButton("Seçili Aracı Aç");go.clicked.connect(self.open_current);row.addWidget(go)
        nov=QPushButton("NOVA Dizin Yönetimi");nov.clicked.connect(lambda: OSSNovaAdminDialog(browser).exec());row.addWidget(nov)
        close=QPushButton("Kapat");close.clicked.connect(self.accept);row.addWidget(close);root.addLayout(row)
        self.search.textChanged.connect(self.refresh);self.list.itemDoubleClicked.connect(lambda *_:self.open_current());self.refresh()
    def refresh(self):
        q=self.search.text().casefold().strip();self.list.clear()
        for key,title,desc in _OSS22_FEATURES:
            if q and q not in (title+" "+desc).casefold():continue
            item=QListWidgetItem(title+"\n"+desc);item.setData(Qt.ItemDataRole.UserRole,key);self.list.addItem(item)
        if self.list.count():self.list.setCurrentRow(0)
    def open_current(self):
        item=self.list.currentItem()
        if not item:return
        key=item.data(Qt.ItemDataRole.UserRole);self.accept();QTimer.singleShot(0,lambda k=key:_oss22_dispatch(self.browser,k))


def _oss22_add_menu(self):
    try:
        button=getattr(self,"tools_button",None);menu=button.menu() if button else None
        if menu is None:return
        if getattr(self,"_oss22_menu_added",False):return
        self._oss22_menu_added=True;menu.addSeparator();menu.addAction("OSS 2.2 — 40 Yeni Özellik",lambda:OSS22FeatureCenter(self).exec());menu.addAction("NOVA Hızlı Dizin Yönetimi",lambda:OSSNovaAdminDialog(self).exec())
        sub=menu.addMenu("OSS 2.2 Hızlı Araçlar")
        quick=[("RSS / Haber Okuyucu","rss"),("Alan Adı İnceleyicisi","domain"),("NOVA Dizin Bakımı","maintenance"),("SHA-256 Doğrulayıcı","checksum"),("Sayfayı PDF kaydet","print"),("Sayfayı CSV tabloya çıkar","tables"),("Özellik Test Laboratuvarı","test_lab")]
        for title,key in quick:sub.addAction(title,lambda _=False,k=key:_oss22_dispatch(self,k))
    except Exception as exc:
        try:self.statusBar().showMessage("OSS 2.2 menüsü eklenemedi: "+str(exc),3500)
        except Exception:pass


_oss22_base_setup_ui = MainWindow.setup_ui
def _oss22_setup_ui(self,*args,**kwargs):
    _oss22_base_setup_ui(self,*args,**kwargs)
    _oss22_add_menu(self)
MainWindow.setup_ui = _oss22_setup_ui

# If older 2.1 tools are added by a later setup wrapper, attach our center to the
# already-created menu after the UI event loop starts as an additional safeguard.
_oss22_base_main_init = MainWindow.__init__
def _oss22_main_init(self,*args,**kwargs):
    _oss22_base_main_init(self,*args,**kwargs)
    QTimer.singleShot(300,lambda b=self:_oss22_add_menu(b))
MainWindow.__init__ = _oss22_main_init

# Event automation rules are intentionally opt-in and local only.
_oss22_base_page_loaded = MainWindow.page_loaded
def _oss22_page_loaded(self,tab):
    _oss22_base_page_loaded(self,tab)
    try:
        url=tab.view.url().toString(); parsed=urlparse(url); host=(parsed.hostname or "").lower().removeprefix("www.")
        if url.startswith(("http://", "https://")) and host != NOVA_SEARCH_HOST:
            tab._nova_live_query = ""
        if not host:return
        rules=self.data.get("oss22_event_rules",[]); fired=self.data.setdefault("oss22_rule_last_fired",{})
        for i,rule in enumerate(rules):
            domain=str(rule.get("domain","")).lower().removeprefix("www.")
            if not rule.get("enabled",True) or not domain or not (host==domain or host.endswith("."+domain)):continue
            now=int(time.time())
            if now-int(fired.get(str(i),0))<300:continue
            fired[str(i)]=now
            if rule.get("action")=="open_url" and str(rule.get("target","")).startswith(("https://","http://")):
                QTimer.singleShot(0,lambda target=rule["target"]:self.new_tab(target))
            else:self.statusBar().showMessage("OSS otomasyonu: " + domain + " ziyaret edildi.",5000)
        if rules:self.save()
    except Exception:pass
MainWindow.page_loaded = _oss22_page_loaded

# Load personal result ranking on each new browser instance and keep it local.
_oss22_base_browser_init_final = MainWindow.__init__
def _oss22_init_load_preferences(self,*args,**kwargs):
    _oss22_base_browser_init_final(self,*args,**kwargs)
    try:
        s=self.data.get("settings",{})
        global _OSS22_PREFERRED_DOMAINS,_OSS22_EXCLUDED_DOMAINS
        _OSS22_PREFERRED_DOMAINS=set(s.get("nova_preferred_domains",[]));_OSS22_EXCLUDED_DOMAINS=set(s.get("nova_excluded_domains",[]))
    except Exception:pass
MainWindow.__init__ = _oss22_init_load_preferences

APP_VERSION = "7.0.0"




# =====================================================================
# NOVAOS V7 — single-page start screen, 50 tools and faster NOVA indexing
# =====================================================================
import ast as _novaosv7_ast
import operator as _novaosv7_operator
import socket as _novaosv7_socket
import ssl as _novaosv7_ssl
import csv as _novaosv7_csv
from urllib.parse import urlencode as _novaosv7_urlencode, parse_qsl as _novaosv7_parse_qsl

APP_NAME = "NOVAOS V7"
APP_VERSION = "7.0.0"
NOVAOSV7_NAME = "novaosv7"
NOVAOSV7_MAX_PENDING = 30000
NOVAOSV7_LINKS_PER_PAGE = 24
NOVAOSV7_FETCH_TIMEOUT = 5.5
NOVAOSV7_MAX_RESPONSE_BYTES = 900000
NOVAOSV7_HOST_DELAY = 0.12
NOVA_WORKERS = 6
NOVA_MAX_PAGES = 12000
NOVA_MAX_DEPTH = 3
NOVA_PAGE_SIZE = 50

_NOVAOSV7_FETCH_LOCK = threading.Lock()
_NOVAOSV7_HOST_LAST = {}
_NOVAOSV7_FTS_LOCK = threading.Lock()
_NOVAOSV7_FTS_CHECKED = False
_NOVAOSV7_LANGUAGE_FALLBACK_USED = False

# Persistent SQLite tuning. Rebuild FTS once per process/version, not on each
# connection. Existing page and queue data are preserved.
_NOVAOSV7_BASE_DB_CONNECT = _nova_db_connect
_NOVAOSV7_SCHEMA_LOCK = threading.Lock()
_NOVAOSV7_SCHEMA_READY = False

def _nova_db_connect_novaosv7():
    """Fast connection path: schema checks and FTS repair run once per process."""
    global _NOVAOSV7_FTS_CHECKED, _NOVAOSV7_SCHEMA_READY, NOVA_FTS5_ENABLED
    # Every call uses a lightweight SQLite connection. WAL/cache settings are per connection.
    conn = sqlite3.connect(str(NOVA_DB), timeout=30, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-24000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=134217728")
    if _NOVAOSV7_SCHEMA_READY:
        return conn
    with _NOVAOSV7_SCHEMA_LOCK:
        if _NOVAOSV7_SCHEMA_READY:
            return conn
        try:
            conn.close()
        except Exception:
            pass
        # One-time base setup creates the pages table and its ordinary indexes.
        conn = _NOVAOSV7_BASE_DB_CONNECT()
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-24000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=134217728")
        conn.execute("CREATE TABLE IF NOT EXISTS nova_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("""CREATE TABLE IF NOT EXISTS nova_crawl_queue (
            url TEXT PRIMARY KEY, depth INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'discovered',
            added_at INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL DEFAULT 0)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nova_queue_status ON nova_crawl_queue(status, depth, added_at)")
        conn.execute("""CREATE TABLE IF NOT EXISTS nova_links (
            source_url TEXT NOT NULL, target_url TEXT NOT NULL,
            PRIMARY KEY(source_url,target_url))""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nova_links_target ON nova_links(target_url)")
        conn.execute("""CREATE TABLE IF NOT EXISTS nova_deferred_queue (
            url TEXT PRIMARY KEY, depth INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'discovered', added_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nova_deferred_depth ON nova_deferred_queue(depth, added_at)")
        try:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(url UNINDEXED,title,snippet,content,domain UNINDEXED,category UNINDEXED,tokenize='unicode61 remove_diacritics 2')")
            conn.execute("""CREATE TRIGGER IF NOT EXISTS nova_pages_ai AFTER INSERT ON pages BEGIN
                INSERT INTO pages_fts(rowid,url,title,snippet,content,domain,category)
                VALUES(new.id,new.url,new.title,new.snippet,new.content,new.domain,new.category); END""")
            conn.execute("""CREATE TRIGGER IF NOT EXISTS nova_pages_au AFTER UPDATE ON pages BEGIN
                DELETE FROM pages_fts WHERE rowid=old.id;
                INSERT INTO pages_fts(rowid,url,title,snippet,content,domain,category)
                VALUES(new.id,new.url,new.title,new.snippet,new.content,new.domain,new.category); END""")
            conn.execute("""CREATE TRIGGER IF NOT EXISTS nova_pages_ad AFTER DELETE ON pages BEGIN
                DELETE FROM pages_fts WHERE rowid=old.id; END""")
            # Do this relatively expensive consistency check once, not on every connection.
            page_count = int(conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0])
            fts_count = int(conn.execute("SELECT COUNT(*) FROM pages_fts").fetchone()[0])
            marker = conn.execute("SELECT value FROM nova_meta WHERE key='fts_rebuild_version'").fetchone()
            if page_count != fts_count or not marker or marker[0] != APP_VERSION:
                conn.execute("INSERT INTO pages_fts(pages_fts) VALUES('rebuild')")
                conn.execute("INSERT INTO nova_meta(key,value) VALUES('fts_rebuild_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (APP_VERSION,))
            NOVA_FTS5_ENABLED = True
        except sqlite3.DatabaseError:
            NOVA_FTS5_ENABLED = False
        conn.commit()
        _NOVAOSV7_FTS_CHECKED = True
        _NOVAOSV7_SCHEMA_READY = True
        return conn

_nova_db_connect = _nova_db_connect_novaosv7

_NOVAOSV7_BASE_CRAWLER_SNAPSHOT = _NovaCrawler.snapshot
def _novaosv7_crawler_snapshot(self):
    snap = _NOVAOSV7_BASE_CRAWLER_SNAPSHOT(self)
    try:
        conn = _nova_db_connect()
        pending = int(conn.execute("SELECT COUNT(*) FROM nova_crawl_queue WHERE status IN ('pending','in_progress')").fetchone()[0])
        deferred = int(conn.execute("SELECT COUNT(*) FROM nova_deferred_queue").fetchone()[0])
        conn.close()
        snap['pending'] = pending
        snap['deferred'] = deferred
        snap['queued'] = pending + deferred
    except Exception:
        snap.setdefault('deferred', 0)
    return snap
_NovaCrawler.snapshot = _novaosv7_crawler_snapshot

# Faster fetch path: smaller cap, shorter timeout, compressed responses and a
# small per-host start interval to avoid hammering one domain.
_NOVAOSV7_BASE_FETCH_PAGE = _nova_fetch_page
def _nova_fetch_page_novaosv7(url):
    try:
        host = (urlparse(url).hostname or "").lower()
        if host:
            with _NOVAOSV7_FETCH_LOCK:
                now = time.monotonic()
                start_at = max(now, _NOVAOSV7_HOST_LAST.get(host, 0.0))
                _NOVAOSV7_HOST_LAST[host] = start_at + NOVAOSV7_HOST_DELAY
                wait = start_at - now
            if wait > 0:
                time.sleep(wait)
        request = urllib.request.Request(url, headers={
            "User-Agent": NOVA_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.3",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
            "Accept-Encoding": "gzip",
            "Connection": "keep-alive",
        })
        with urllib.request.urlopen(request, timeout=NOVAOSV7_FETCH_TIMEOUT) as response:
            ctype = (response.headers.get("Content-Type") or "").lower()
            if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
                return None
            length = response.headers.get("Content-Length")
            if length:
                try:
                    if int(length) > NOVAOSV7_MAX_RESPONSE_BYTES * 5:
                        return None
                except Exception:
                    pass
            if (response.headers.get("Content-Encoding") or "").lower() == "gzip":
                # GzipFile reads compressed bytes as needed and caps the decoded body,
                # avoiding the old failure where a truncated gzip stream was undecodable.
                with gzip.GzipFile(fileobj=response) as compressed:
                    raw = compressed.read(NOVAOSV7_MAX_RESPONSE_BYTES)
            else:
                raw = response.read(NOVAOSV7_MAX_RESPONSE_BYTES)
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, "ignore")
    except Exception:
        return None

_nova_fetch_page = _nova_fetch_page_novaosv7

# Make newly discovered pages and the search index visible together. We keep
# one ThreadPoolExecutor alive and commit each group in one SQLite transaction.
def _nova_fetch_job_novaosv7(url, depth, roots):
    try:
        safe = _nova_safe_crawl_url(url, roots)
        if not safe:
            return {"url": url, "depth": depth, "row": None, "error": "URL izinli kaynak kapsamı dışında."}
        raw = _nova_fetch_page(safe)
        if not raw:
            return {"url": safe, "depth": depth, "row": None, "error": "HTML alınamadı; kaynak erişimi reddetmiş veya zaman aşımı olmuş olabilir."}
        row = _nova_extract_page(safe, raw)
        row["depth"] = int(depth or 0)
        allowed, seen = [], set()
        for link in row.get("links", []):
            candidate = _nova_safe_crawl_url(link, roots)
            if candidate and candidate not in seen:
                seen.add(candidate); allowed.append(candidate)
                if len(allowed) >= NOVAOSV7_LINKS_PER_PAGE:
                    break
        row["links"] = allowed
        return {"url": safe, "depth": depth, "row": row, "error": ""}
    except Exception as exc:
        return {"url": url, "depth": depth, "row": None, "error": str(exc)[:240]}


def _nova_crawler_run_novaosv7(self):
    scanned = 0
    pool = None
    conn = None
    try:
        roots_urls = list(dict.fromkeys(list(NOVA_SEEDS) + list(getattr(self, "extra_seeds", []))))
        roots = _nova_roots_from_urls(roots_urls)
        conn = _nova_db_connect()
        conn.execute("UPDATE nova_crawl_queue SET status='pending',updated_at=? WHERE status='in_progress'", (int(time.time()),))
        now = int(time.time())
        for seed in roots_urls:
            safe = _nova_safe_crawl_url(seed, roots)
            if safe:
                _nova_queue_add(conn, safe, 0, "seed" if seed in NOVA_SEEDS else "user", requeue=False)
        # Full reindex only runs when explicitly requested by the user.
        if bool(getattr(self, "force_requested", False)):
            conn.execute("UPDATE nova_crawl_queue SET status='pending',last_error='',updated_at=? WHERE status IN ('done','error')", (now,))
            self.force_requested = False
        conn.commit()
        conn.close(); conn = None

        worker_count = max(1, min(8, int(getattr(self, "worker_count", NOVA_WORKERS))))
        session_limit = max(100, min(50000, int(getattr(self, "session_limit", NOVA_MAX_PAGES))))
        pool = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="NOVAOSV7-Fetch")
        pending_cap = NOVAOSV7_MAX_PENDING

        while scanned < session_limit:
            with self.lock:
                if self.stop_flag:
                    break
                dynamic_urls = list(getattr(self, "extra_seeds", []))
            active_roots = _nova_roots_from_urls(list(NOVA_SEEDS) + dynamic_urls)
            conn = _nova_db_connect()
            pending_count = int(conn.execute("SELECT COUNT(*) FROM nova_crawl_queue WHERE status='pending'").fetchone()[0])
            if pending_count < pending_cap:
                vacancy = pending_cap - pending_count
                deferred_rows = conn.execute("SELECT url,depth,source,added_at,updated_at FROM nova_deferred_queue ORDER BY depth ASC,added_at ASC LIMIT ?", (min(vacancy, 1200),)).fetchall()
                if deferred_rows:
                    conn.executemany("INSERT OR IGNORE INTO nova_crawl_queue(url,depth,status,attempts,last_error,source,added_at,updated_at) VALUES(?,?,'pending',0,'',?,?,?)", deferred_rows)
                    conn.executemany("DELETE FROM nova_deferred_queue WHERE url=?", [(r[0],) for r in deferred_rows])
                    conn.commit()
            batch_size = min(max(worker_count * 3, worker_count), session_limit - scanned, 36)
            batch = conn.execute("SELECT url,depth FROM nova_crawl_queue WHERE status='pending' ORDER BY depth ASC, added_at ASC LIMIT ?", (batch_size,)).fetchall()
            if not batch:
                conn.close(); conn = None
                break
            now = int(time.time())
            conn.executemany("UPDATE nova_crawl_queue SET status='in_progress',attempts=attempts+1,updated_at=? WHERE url=? AND status='pending'", [(now, row[0]) for row in batch])
            conn.commit(); conn.close(); conn = None

            futures = {pool.submit(_nova_fetch_job_novaosv7, url, int(depth or 0), set(active_roots)): (url, int(depth or 0)) for url, depth in batch}
            results = []
            for future in as_completed(futures):
                original_url, original_depth = futures[future]
                scanned += 1
                try:
                    item = future.result()
                except Exception as exc:
                    item = {"url": original_url, "depth": original_depth, "row": None, "error": str(exc)[:240]}
                results.append(item)
                if scanned >= session_limit:
                    with self.lock:
                        self.stop_flag = True

            # One writer connection/transaction per completed batch; FTS triggers
            # index new rows on commit, so search pages see the new rows promptly.
            conn = _nova_db_connect()
            stamp = int(time.time())
            successful = [x for x in results if x.get("row")]
            failures = [x for x in results if not x.get("row")]
            if successful:
                values = []
                all_links = []
                children = []
                for item in successful:
                    row = item["row"]
                    values.append((row["url"], row["title"], row["snippet"], row["content"], row["domain"], row["category"], stamp, int(row.get("depth", 0))))
                    for target in row.get("links", []):
                        all_links.append((row["url"], target))
                        if int(row.get("depth", 0)) < NOVA_MAX_DEPTH:
                            children.append((target, int(row["depth"]) + 1, "discovered", stamp, stamp))
                conn.executemany("""INSERT INTO pages(url,title,snippet,content,domain,category,crawled_at,depth)
                    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET title=excluded.title,snippet=excluded.snippet,content=excluded.content,domain=excluded.domain,category=excluded.category,crawled_at=excluded.crawled_at,depth=excluded.depth""", values)
                conn.executemany("UPDATE nova_crawl_queue SET status='done',last_error='',updated_at=? WHERE url=?", [(stamp, item["row"]["url"]) for item in successful])
                if all_links:
                    conn.executemany("INSERT OR IGNORE INTO nova_links(source_url,target_url) VALUES(?,?)", all_links)
                current_pending = int(conn.execute("SELECT COUNT(*) FROM nova_crawl_queue WHERE status='pending'").fetchone()[0])
                if children:
                    # Active queue stays bounded, but overflow is saved, not discarded.
                    capacity = max(0, pending_cap - current_pending)
                    active_children = children[:capacity]
                    deferred_children = children[capacity:]
                    if active_children:
                        conn.executemany("INSERT OR IGNORE INTO nova_crawl_queue(url,depth,status,attempts,last_error,source,added_at,updated_at) VALUES(?,?,'pending',0,'',?,?,?)", active_children)
                    if deferred_children:
                        conn.executemany("INSERT OR IGNORE INTO nova_deferred_queue(url,depth,source,added_at,updated_at) VALUES(?,?,?,?,?)", deferred_children)
                conn.commit()
                with self.lock:
                    self.pages += len(successful)
            if failures:
                for item in failures:
                    err = str(item.get("error") or "İçerik alınamadı.")[:300]
                    conn.execute("UPDATE nova_crawl_queue SET status='error',last_error=?,updated_at=? WHERE url=?", (err, stamp, item.get("url", "")))
                conn.commit()
                with self.lock:
                    self.errors += len(failures)
            self.queued = int(conn.execute("SELECT COUNT(*) FROM nova_crawl_queue WHERE status IN ('pending','in_progress')").fetchone()[0])
            conn.close(); conn = None
    except Exception as exc:
        try:
            with self.lock:
                self.errors += 1
            setattr(self, "last_error", str(exc)[:300])
        except Exception:
            pass
    finally:
        if conn is not None:
            try:
                conn.execute("UPDATE nova_crawl_queue SET status='pending',updated_at=? WHERE status='in_progress'", (int(time.time()),))
                conn.commit(); conn.close()
            except Exception:
                try: conn.close()
                except Exception: pass
        if pool is not None:
            try: pool.shutdown(wait=False, cancel_futures=True)
            except Exception: pass
        try:
            done_conn = _nova_db_connect()
            done_conn.execute("UPDATE nova_crawl_queue SET status='pending',updated_at=? WHERE status='in_progress'", (int(time.time()),))
            self.queued = int(done_conn.execute("SELECT COUNT(*) FROM nova_crawl_queue WHERE status='pending'").fetchone()[0])
            done_conn.commit(); done_conn.close()
        except Exception:
            pass
        with self.lock:
            self.running = False
            self.stop_flag = False

# Worker remains persistent for the whole batch loop, and all page writes are grouped.
_NOVAOSV7_PREV_CRAWLER_RUN = _NovaCrawler._run
_NovaCrawler._run = _nova_crawler_run_novaosv7

_NOVAOSV7_BASE_CRAWLER_START = _NovaCrawler.start
def _novaosv7_crawler_start_limited(self, force=False, extra_seeds=None, worker_count=None, session_limit=None):
    """Start the current optimized worker; never call the legacy _run directly."""
    workers = max(1, min(8, int(worker_count or NOVA_WORKERS)))
    limit = max(100, min(50000, int(session_limit or NOVA_MAX_PAGES)))
    with self.lock:
        if self.running:
            already_running = True
        else:
            already_running = False
            self.stop_flag = False
            self.running = True
            self.pages = 0
            self.errors = 0
            self.force_requested = bool(force)
            self.worker_count = workers
            self.session_limit = limit
    if already_running:
        if extra_seeds:
            try:
                self.add_seeds(extra_seeds, requeue=True)
            except Exception:
                pass
        return False
    self.extra_seeds = list(getattr(self, "extra_seeds", []))
    if extra_seeds:
        try:
            self.add_seeds(extra_seeds, requeue=False)
        except Exception:
            pass
    self.thread = threading.Thread(target=self._run, daemon=True, name="NOVAOSV7-Indexer")
    self.thread.start()
    return True
_NovaCrawler.start = _novaosv7_crawler_start_limited

# Search fallback: when strict AND or the Turkish-only filter hides all results,
# progressively relax language then use individual terms. Results still come from
# the local SQLite index, never from an external search page.
_NOVAOSV7_BASE_SEARCH_DB = _nova_search_db
def _nova_search_db_novaosv7(query, page=1, limit=NOVA_PAGE_SIZE, language_filter="turkish_only", category_filter="all", recency_filter="any"):
    global _NOVAOSV7_LANGUAGE_FALLBACK_USED
    _NOVAOSV7_LANGUAGE_FALLBACK_USED = False
    result, total = _NOVAOSV7_BASE_SEARCH_DB(query, page, limit, language_filter, category_filter, recency_filter)
    if result or total:
        return result, total
    if language_filter == "turkish_only":
        result, total = _NOVAOSV7_BASE_SEARCH_DB(query, page, limit, "all", category_filter, recency_filter)
        if result or total:
            _NOVAOSV7_LANGUAGE_FALLBACK_USED = True
            return result, total
    # If every token was required by FTS and that is too strict, merge results
    # from each useful token and rank by how many query words match.
    parts = []
    for token in re.findall(r"[\wğüşöçıİĞÜŞÖÇ-]{2,}", str(query or ""), flags=re.UNICODE):
        if token.lower() in {"site", "intitle", "after", "before", "filetype"}:
            continue
        if token not in parts:
            parts.append(token)
    if len(parts) <= 1:
        return [], 0
    mode = "all" if language_filter == "turkish_only" else language_filter
    merged = {}
    for token in parts[:6]:
        try:
            rows, _ = _NOVAOSV7_BASE_SEARCH_DB(token, 1, min(80, max(30, limit * 2)), mode, category_filter, recency_filter)
        except Exception:
            rows = []
        for item in rows:
            url = item.get("url", "")
            if not url:
                continue
            entry = merged.setdefault(url, dict(item, _hits=0))
            entry["_hits"] += 1
    if not merged:
        return [], 0
    terms_lower = [x.lower() for x in parts]
    def rank(item):
        hay = (item.get("title", "") + " " + item.get("snippet", "") + " " + item.get("url", "")).lower()
        return (item.get("_hits", 0), sum(1 for t in terms_lower if t in hay), item.get("title", "").lower())
    ranked = sorted(merged.values(), key=rank, reverse=True)
    total = len(ranked)
    start = (max(1, int(page or 1)) - 1) * max(1, int(limit or NOVA_PAGE_SIZE))
    return [{k:v for k,v in item.items() if k != "_hits"} for item in ranked[start:start + max(1, int(limit or NOVA_PAGE_SIZE))]], total

_nova_search_db = _nova_search_db_novaosv7

# Final compact single-page home — removes the Discover content blocks and keeps
# search, engine selection, index status and useful actions on a single viewport.
def _nova_home_html_novaosv7(engine_name="NOVA Search", shortcuts=None, browser=None):
    if engine_name not in SEARCH_ENGINES:
        engine_name = NOVA_SEARCH_NAME
    snap = _nova_status_snapshot(browser) if browser is not None else {}
    indexed = int(snap.get("indexed", 0) or 0)
    queued = int(snap.get("queued", 0) or 0)
    errors = int(snap.get("failed", 0) or 0)
    workers = int(snap.get("workers", NOVA_WORKERS) or NOVA_WORKERS)
    running = bool(snap.get("running", False))
    fts = bool(snap.get("fts5", NOVA_FTS5_ENABLED))
    engine_options = []
    for name in ("NOVA Search", "Google", "Bing", "DuckDuckGo"):
        sel = " selected" if name == engine_name else ""
        engine_options.append(f'<option value="{html.escape(name, quote=True)}"{sel}>{html.escape(name)}</option>')
    shortcuts_html = []
    source_shortcuts = shortcuts if isinstance(shortcuts, list) else DEFAULT_HOME_SHORTCUTS
    for item in source_shortcuts:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "Site")).strip()[:40]
        url = str(item.get("url", "")).strip()
        icon = str(item.get("icon", "↗")).strip()[:8] or "↗"
        if is_web_url(url):
            shortcuts_html.append('<a class="shortcut" href="' + html.escape(url, quote=True) + '"><span>' + html.escape(icon) + '</span><b>' + html.escape(title) + '</b><small>' + html.escape(_nova_domain(url)) + '</small></a>')
        if len(shortcuts_html) >= 5:
            break
    if not shortcuts_html:
        shortcuts_html = ['<a class="shortcut" href="https://www.youtube.com/"><span>▶</span><b>YouTube</b><small>youtube.com</small></a>', '<a class="shortcut" href="https://github.com/"><span>⌘</span><b>GitHub</b><small>github.com</small></a>']
    state = "İndeksleniyor" if running else ("Kuyrukta iş var" if queued else "Hazır")
    template = r"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><title>NOVAOS V7</title>
<style>
:root{color-scheme:dark;--bg:#080a10;--panel:#111722;--panel2:#0c111a;--line:#253145;--muted:#8b98ae;--text:#f4f7ff;--purple:#8b6bff;--blue:#51c5ff;--green:#55e0b0}*{box-sizing:border-box}html,body{margin:0;width:100%;min-height:100%;font-family:Segoe UI,Inter,Arial,sans-serif;color:var(--text);background:var(--bg)}body{height:100vh;overflow:auto;background:radial-gradient(ellipse at 50% -18%,#1d2d53 0%,transparent 49%),linear-gradient(160deg,#090c14,#05070c 70%)}a{color:inherit;text-decoration:none}.root{min-height:100vh;display:flex;flex-direction:column;width:min(1120px,94vw);margin:auto;padding:22px 0 14px}.header{display:flex;align-items:center;justify-content:space-between;gap:16px}.brand{display:flex;align-items:center;gap:12px}.logo{width:43px;height:43px;display:grid;place-items:center;border-radius:13px;background:linear-gradient(145deg,#a18aff,#52c8ff);font-weight:1000;font-size:23px;color:#070a12;box-shadow:0 8px 30px #7163ff35}.brand b{display:block;font-size:16px;letter-spacing:.4px}.brand small{display:block;margin-top:4px;color:#7f8ba3;font-size:10px;letter-spacing:1.4px}.status{display:flex;align-items:center;gap:8px;color:#bdc9dc;background:#111927;border:1px solid var(--line);padding:9px 12px;border-radius:999px;font-size:11px}.dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 13px #55e0b050}.hero{width:min(780px,100%);margin:auto;text-align:center;padding:48px 0 30px}.tag{display:inline-flex;align-items:center;gap:8px;padding:7px 11px;border:1px solid #8b6bff45;background:#8b6bff12;color:#c4b8ff;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:1.5px}.tag .dot{background:var(--blue)}h1{margin:19px 0 12px;font-size:clamp(39px,6vw,65px);line-height:1;letter-spacing:-2.6px;font-weight:900}h1 span{background:linear-gradient(95deg,#a18aff,#66caff 62%,#68e6ce);color:transparent;background-clip:text}.intro{margin:0 auto 27px;color:#9aa8bf;font-size:13px;line-height:1.65;max-width:580px}.search{display:flex;gap:8px;align-items:center;padding:7px;border:1px solid #4d4779;border-radius:18px;background:#0f1521;box-shadow:0 15px 55px #0008,0 0 0 4px #8b6bff0b}.search:focus-within{border-color:#8b6bff;box-shadow:0 0 0 4px #8b6bff20}.magnify{color:#8fa3c3;font-size:22px;padding-left:11px}.search input{flex:1;min-width:0;border:0;outline:0;background:transparent;color:#f7f8ff;font-size:15px;padding:13px 4px}.search input::placeholder{color:#67758e}.search select{max-width:142px;border:1px solid #28344a;border-radius:10px;padding:10px 9px;background:#111c2c;color:#ced8ec;outline:0}.search button{border:0;border-radius:12px;background:linear-gradient(135deg,var(--purple),#4c9fff);padding:13px 22px;color:#fff;font-size:12px;font-weight:850;cursor:pointer}.search button:hover{filter:brightness(1.12)}.hint{font-size:10px;color:#64738b;margin-top:12px}.key{border:1px solid #2d394e;background:#121a28;border-radius:5px;padding:2px 6px;color:#a4b1c9}.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:34px;text-align:left}.stat{background:linear-gradient(145deg,#111a28,#0c111a);border:1px solid var(--line);border-radius:14px;padding:14px 15px;min-width:0}.stat label{display:block;color:#7888a2;font-size:10px;margin-bottom:7px}.stat strong{font-size:21px;letter-spacing:-.5px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.stat small{font-size:10px;color:#77869f;display:block;margin-top:5px}.actions{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin-top:16px}.action{display:flex;align-items:center;gap:9px;padding:12px 13px;border:1px solid var(--line);border-radius:12px;background:#0e1420;color:#dce5f5;font-size:11px;font-weight:750;transition:all .15s}.action:hover{border-color:#7462d8;background:#15192c;transform:translateY(-1px)}.action .ico{width:28px;height:28px;display:grid;place-items:center;border-radius:8px;background:#202a3f;color:#b9c6ff;font-size:14px;flex:none}.quick-head{display:flex;justify-content:space-between;align-items:center;margin:26px 1px 10px;color:#8b99b0;font-size:10px;font-weight:800;letter-spacing:1px;text-transform:uppercase}.quick-head a{color:#a99aff;letter-spacing:0;text-transform:none;font-size:10px}.shortcuts{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.shortcut{min-width:0;display:grid;grid-template-columns:28px 1fr;grid-template-rows:auto auto;column-gap:9px;align-items:center;padding:10px;border:1px solid #202b3d;border-radius:11px;background:#0c111a}.shortcut:hover{border-color:#554a96;background:#111729}.shortcut span{grid-row:1/3;width:28px;height:28px;display:grid;place-items:center;border-radius:8px;background:#1b2739;color:#a9bcff;font-size:12px;font-weight:900}.shortcut b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:10px}.shortcut small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:9px;color:#76869f;margin-top:3px}.footer{display:flex;align-items:center;justify-content:space-between;gap:12px;border-top:1px solid #1d2738;padding-top:12px;color:#5f6d83;font-size:10px}.footer span{white-space:nowrap}.footer a{color:#8f9fba}.footer a:hover{color:#fff}@media(max-width:760px){.hero{padding:40px 0 22px}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.actions{grid-template-columns:repeat(2,minmax(0,1fr))}.shortcuts{grid-template-columns:repeat(2,minmax(0,1fr))}.search{flex-wrap:wrap}.search input{min-width:45%}.search select{max-width:none}.footer{flex-wrap:wrap}}@media(max-height:760px) and (min-width:761px){.root{padding-top:16px}.hero{padding:24px 0 20px}.intro{margin-bottom:18px}h1{font-size:53px;margin:14px 0 9px}.stats{margin-top:23px}.quick-head{margin-top:18px}}
</style></head><body><div class="root"><header class="header"><div class="brand"><div class="logo">N</div><div><b>NOVAOS V7</b><small>LOCAL SEARCH ENGINE · V7.0.0</small></div></div><div class="status"><i class="dot" id="stateDot"></i><span id="stateText">@STATE@</span></div></header><main class="hero"><div class="tag"><i class="dot"></i> KENDİ İNDEKSİN · KENDİ KONTROLÜN</div><h1>Aradığını bul.<br><span>Kontrol sende.</span></h1><p class="intro">Yerel web dizininde ara veya Google, Bing ve DuckDuckGo'ya geç. Yeni sayfalar indekslendikçe sonuçlar güncellenir.</p><form class="search" id="searchForm" action="https://ossbrowser.local/submit" method="get"><span class="magnify">⌕</span><input id="query" name="q" type="search" autocomplete="off" placeholder="Minecraft, Python, site:python.org, filetype:pdf…" autofocus><select id="engine" name="engine">@ENGINES@</select><button type="submit">Ara ↗</button></form><div class="hint"><span class="key">Enter</span> ara · <span class="key">/</span> kutuya geç · <span class="key">Ctrl K</span> araç merkezi</div><section class="stats"><div class="stat"><label>İndekslenmiş sayfa</label><strong id="statIndexed">@INDEXED@</strong><small>FTS tam metin araması: <span id="ftsState">@FTS@</span></small></div><div class="stat"><label>Bekleyen tarama</label><strong id="statQueued">@QUEUED@</strong><small>Kaynak başına sınırlı bağlantı kuyruğu</small></div><div class="stat"><label>Tarama işçisi</label><strong id="statWorkers">@WORKERS@</strong><small>Paralel HTTP istekleri</small></div><div class="stat"><label>Son durum</label><strong id="statState">@STATE@</strong><small><span id="statFailed">@FAILED@</span> başarısız URL</small></div></section><section class="actions"><a class="action" href="https://ossbrowser.local/admin"><span class="ico">▦</span>Dizin yönetimi</a><a class="action" href="https://ossbrowser.local/reindex"><span class="ico">↻</span>Yeni sayfaları tara</a><a class="action" href="https://ossbrowser.local/tools"><span class="ico">⌘</span>50 araç merkezi</a><a class="action" href="https://ossbrowser.local/history"><span class="ico">◷</span>Geçmiş ve oturum</a></section><div class="quick-head"><span>Hızlı bağlantılar</span><a href="https://ossbrowser.local/tools?key=home">Düzenleme araçları ↗</a></div><section class="shortcuts">@SHORTCUTS@</section></main><footer class="footer"><span>NOVAOS V7 · Yerel SQLite + FTS5</span><span>Sonuçlar yalnızca dizine alınmış sayfalardan gelir.</span><span><a href="https://ossbrowser.local/tools">Araçlar</a> · <a href="https://ossbrowser.local/admin">İndeksi yönet</a></span></footer></div><script>
(function(){const form=document.getElementById('searchForm'),engine=document.getElementById('engine'),query=document.getElementById('query');form.addEventListener('submit',function(e){e.preventDefault();const q=query.value.trim();if(!q)return;location.href='https://ossbrowser.local/submit?engine='+encodeURIComponent(engine.value)+'&q='+encodeURIComponent(q);});document.addEventListener('keydown',function(e){if(e.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){e.preventDefault();query.focus();}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();location.href='https://ossbrowser.local/tools';}});function clock(){const n=new Date();const el=document.getElementById('stateText');if(el){const state='@STATE@';el.title=n.toLocaleString('tr-TR');}}clock();})();
</script></body></html>"""
    return (template.replace('@STATE@', html.escape(state))
        .replace('@INDEXED@', f'{indexed:,}'.replace(',', '.'))
        .replace('@QUEUED@', f'{queued:,}'.replace(',', '.'))
        .replace('@FAILED@', f'{errors:,}'.replace(',', '.'))
        .replace('@WORKERS@', str(workers))
        .replace('@FTS@', 'Açık' if fts else 'LIKE')
        .replace('@ENGINES@', ''.join(engine_options))
        .replace('@SHORTCUTS@', ''.join(shortcuts_html)))

_nova_home_html = _nova_home_html_novaosv7

# Show a result even if the Turkish-only filter was too strict. The query still
# searches only the local index; an all-language fallback is used only on zero hits.
_NOVAOSV7_BASE_RESULT_HTML = _nova_result_html
def _nova_result_html_novaosv7(browser, query, results, total, page):
    output = _NOVAOSV7_BASE_RESULT_HTML(browser, query, results, total, page)
    if _NOVAOSV7_LANGUAGE_FALLBACK_USED:
        notice = '<div style="padding:10px 12px;border:1px solid #4b427d;background:#19152b;border-radius:10px;color:#d0c6ff;margin:10px 0">Türkçe filtresinde eşleşme bulunamadı; yeni indeks kayıtlarını kaçırmamak için tüm dillerden sonuç gösteriliyor.</div>'
        if '</form>' in output:
            output = output.replace('</form>', '</form>' + notice, 1)
    return output

_nova_result_html = _nova_result_html_novaosv7

# 10 extra functional tools on top of the existing 40-feature tool centre.
def _novaosv7_active_view(browser):
    try: return browser.current_view()
    except Exception: return None

def _novaosv7_notice(browser, title, text):
    _oss22_notice(browser, title, str(text))

def _novaosv7_page_metadata(browser):
    view = _novaosv7_active_view(browser)
    if not view: return
    script = "JSON.stringify({title:document.title,url:location.href,lang:document.documentElement.lang||'',description:(document.querySelector('meta[name=description]')||{}).content||'',canonical:(document.querySelector('link[rel=canonical]')||{}).href||'',ogTitle:(document.querySelector('meta[property=\"og:title\"]')||{}).content||'',ogDescription:(document.querySelector('meta[property=\"og:description\"]')||{}).content||'',charset:document.characterSet||''})"
    def done(raw):
        try:
            data = json.loads(raw or '{}')
            text = '\n'.join(f'{k}: {v}' for k,v in data.items())
        except Exception: text = str(raw)
        _novaosv7_notice(browser, 'Sayfa meta bilgileri', text)
    view.page().runJavaScript(script, done)

def _novaosv7_word_count(browser):
    view = _novaosv7_active_view(browser)
    if not view: return
    script = "JSON.stringify((()=>{const t=(document.body?.innerText||'').trim();return {title:document.title,words:(t.match(/\\S+/g)||[]).length,characters:t.length,links:document.links.length,images:document.images.length,headings:document.querySelectorAll('h1,h2,h3,h4,h5,h6').length,forms:document.forms.length,language:document.documentElement.lang||'belirtilmemiş'};})())"
    def done(raw):
        try: data = json.loads(raw or '{}'); text = '\n'.join(f'{k}: {v}' for k,v in data.items())
        except Exception: text = str(raw)
        _novaosv7_notice(browser, 'Sayfa istatistikleri', text)
    view.page().runJavaScript(script, done)

def _novaosv7_export_links(browser):
    view = _novaosv7_active_view(browser)
    if not view: return
    script = "JSON.stringify(Array.from(document.querySelectorAll('a[href]')).map(a=>({title:(a.innerText||a.getAttribute('aria-label')||'').trim().slice(0,300),url:a.href})).filter(x=>/^https?:/i.test(x.url)).slice(0,5000))"
    def done(raw):
        try: items = json.loads(raw or '[]')
        except Exception: items = []
        if not items:
            QMessageBox.information(browser, 'Bağlantı dışa aktarma', 'Sayfada dışa aktarılabilecek HTTP/HTTPS bağlantısı bulunamadı.'); return
        path, _ = QFileDialog.getSaveFileName(browser, 'Bağlantıları kaydet', 'novaosv7_links.csv', 'CSV (*.csv);;JSON (*.json);;Metin (*.txt)')
        if not path: return
        try:
            if path.lower().endswith('.json'):
                Path(path).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')
            elif path.lower().endswith('.txt'):
                Path(path).write_text('\n'.join(f"{i.get('title','')}\t{i.get('url','')}" for i in items), encoding='utf-8')
            else:
                with open(path,'w',newline='',encoding='utf-8-sig') as f:
                    writer=_novaosv7_csv.DictWriter(f,fieldnames=['title','url']);writer.writeheader();writer.writerows(items)
            QMessageBox.information(browser,'Bağlantılar kaydedildi',f'{len(items)} bağlantı kaydedildi.\n{path}')
        except Exception as exc: QMessageBox.warning(browser,'Bağlantı dışa aktarma',str(exc))
    view.page().runJavaScript(script, done)

def _novaosv7_clean_url(browser):
    raw = _oss22_url_for_browser(browser)
    p = urlparse(raw)
    if p.scheme not in ('http','https'):
        QMessageBox.information(browser,'Bağlantı temizleyici','Önce normal bir web sayfası aç.'); return
    trackers = {'gclid','fbclid','dclid','mc_cid','mc_eid','igshid','ref_src','yclid','vero_id','_hsenc','_hsmi'}
    pairs = [(k,v) for k,v in _novaosv7_parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in trackers]
    cleaned = p._replace(query=_novaosv7_urlencode(pairs, doseq=True), fragment='').geturl()
    QApplication.clipboard().setText(cleaned)
    _novaosv7_notice(browser,'Temiz bağlantı', 'Panoya kopyalandı:\n'+cleaned)

def _novaosv7_copy_page(browser):
    view = _novaosv7_active_view(browser)
    if not view: return
    payload = f'{view.title()}\n{view.url().toString()}'
    QApplication.clipboard().setText(payload)
    browser.statusBar().showMessage('Sayfa başlığı ve URL panoya kopyalandı.', 2500)

def _novaosv7_open_robots(browser):
    p = urlparse(_oss22_url_for_browser(browser))
    if p.scheme not in ('http','https') or not p.netloc:
        QMessageBox.information(browser,'robots.txt','Önce bir web sitesine git.'); return
    browser.new_tab(p._replace(path='/robots.txt',query='',fragment='').geturl())

def _novaosv7_open_sitemap(browser):
    p = urlparse(_oss22_url_for_browser(browser))
    if p.scheme not in ('http','https') or not p.netloc:
        QMessageBox.information(browser,'Sitemap','Önce bir web sitesine git.'); return
    browser.new_tab(p._replace(path='/sitemap.xml',query='',fragment='').geturl())

def _novaosv7_save_html(browser):
    view = _novaosv7_active_view(browser)
    if not view: return
    default = re.sub(r'[^\w.-]+','_',view.title() or 'sayfa')[:70] + '.html'
    path, _ = QFileDialog.getSaveFileName(browser,'Sayfa HTML kaydet',default,'HTML (*.html)')
    if not path: return
    def done(source):
        try:
            Path(path).write_text(source or '',encoding='utf-8')
            QMessageBox.information(browser,'HTML kaydedildi','Sayfanın mevcut DOM çıktısı kaydedildi. Dinamik veya oturum gerektiren içerik tamamen arşivlenmeyebilir.\n'+path)
        except Exception as exc: QMessageBox.warning(browser,'HTML kaydet',str(exc))
    view.page().toHtml(done)

def _novaosv7_timer(browser):
    minutes, ok = QInputDialog.getInt(browser,'Hatırlatıcı','Kaç dakika sonra hatırlatayım?',15,1,1440,1)
    if not ok: return
    def alert():
        try: QMessageBox.information(browser,'NOVAOS V7 hatırlatıcı',f'{minutes} dakika önce başlattığın hatırlatmanın zamanı geldi.')
        except Exception: pass
    QTimer.singleShot(minutes*60*1000, alert)
    browser.statusBar().showMessage(f'{minutes} dakikalık hatırlatıcı kuruldu.', 3000)

def _novaosv7_safe_calculate(expression):
    if len(expression) > 120: raise ValueError('İfade çok uzun.')
    node = _novaosv7_ast.parse(expression, mode='eval')
    ops = {_novaosv7_ast.Add:_novaosv7_operator.add,_novaosv7_ast.Sub:_novaosv7_operator.sub,_novaosv7_ast.Mult:_novaosv7_operator.mul,_novaosv7_ast.Div:_novaosv7_operator.truediv,_novaosv7_ast.FloorDiv:_novaosv7_operator.floordiv,_novaosv7_ast.Mod:_novaosv7_operator.mod,_novaosv7_ast.Pow:_novaosv7_operator.pow}
    unary = {_novaosv7_ast.UAdd:_novaosv7_operator.pos,_novaosv7_ast.USub:_novaosv7_operator.neg}
    def ev(n):
        if isinstance(n,_novaosv7_ast.Expression): return ev(n.body)
        if isinstance(n,_novaosv7_ast.Constant) and isinstance(n.value,(int,float)) and not isinstance(n.value,bool): return n.value
        if isinstance(n,_novaosv7_ast.BinOp) and type(n.op) in ops:
            left,right=ev(n.left),ev(n.right)
            if isinstance(n.op,_novaosv7_ast.Pow) and abs(right)>12: raise ValueError('Üs değeri en fazla 12 olabilir.')
            value=ops[type(n.op)](left,right)
            if isinstance(value,(int,float)) and abs(value)>1e100: raise ValueError('Sonuç sınırı aşıyor.')
            return value
        if isinstance(n,_novaosv7_ast.UnaryOp) and type(n.op) in unary: return unary[type(n.op)](ev(n.operand))
        raise ValueError('Yalnızca sayılar ve + - * / // % ** parantezleri kullanılabilir.')
    return ev(node)

def _novaosv7_calculator(browser):
    expr,ok=QInputDialog.getText(browser,'Hesap Makinesi','İfade (ör. (125*1.2)/3):')
    if not ok or not expr.strip(): return
    try: _novaosv7_notice(browser,'Hesap sonucu',f'{expr} = {_novaosv7_safe_calculate(expr)}')
    except Exception as exc: QMessageBox.warning(browser,'Hesap makinesi',str(exc))

def _novaosv7_url_info(browser):
    view=_novaosv7_active_view(browser); raw=view.url().toString() if view else ''
    p=urlparse(raw)
    lines=[f'Başlık: {view.title() if view else ""}',f'URL: {raw}',f'Protokol: {p.scheme}',f'Alan adı: {p.hostname or ""}',f'Port: {p.port or (443 if p.scheme=="https" else 80 if p.scheme=="http" else "")}',f'HTTPS: {"Evet" if p.scheme=="https" else "Hayır"}']
    if p.username or p.password: lines.append('Uyarı: URL içinde kullanıcı bilgisi var; paylaşmadan önce temizle.')
    _novaosv7_notice(browser,'Geçerli sayfa bilgileri','\n'.join(lines))

def _novaosv7_database_report(browser):
    try:
        conn=_nova_db_connect()
        counts={"İndekslenmiş sayfa":conn.execute('SELECT COUNT(*) FROM pages').fetchone()[0],"Bekleyen URL":conn.execute("SELECT COUNT(*) FROM nova_crawl_queue WHERE status='pending'").fetchone()[0],"Başarısız URL":conn.execute("SELECT COUNT(*) FROM nova_crawl_queue WHERE status='error'").fetchone()[0],"Bağlantı kenarı":conn.execute('SELECT COUNT(*) FROM nova_links').fetchone()[0]}
        conn.close(); size=NOVA_DB.stat().st_size if NOVA_DB.exists() else 0
        text='\n'.join(f'{k}: {v:,}' for k,v in counts.items())+f'\nFTS5: {NOVA_FTS5_ENABLED}\nDB boyutu: {size/1024/1024:.1f} MB\nVeritabanı: {NOVA_DB}'
        _novaosv7_notice(browser,'NOVA veritabanı raporu',text)
    except Exception as exc: QMessageBox.warning(browser,'NOVA raporu',str(exc))

_NOVAOSV7_EXTRA_TOOLS = [
    ("metadata", "Sayfa Meta Verileri", "Başlık, açıklama, canonical URL, Open Graph ve dil bilgisi."),
    ("word_count", "Sayfa İstatistikleri", "Kelime, karakter, bağlantı, görsel ve başlık sayısını ölç."),
    ("export_links", "Bağlantıları CSV/JSON Dışa Aktar", "Açık sayfadaki HTTP/HTTPS bağlantılarını dosyaya kaydet."),
    ("clean_url", "İzleme Parametrelerini Temizle", "UTM ve yaygın izleme parametrelerini ayırıp temiz URL'yi kopyala."),
    ("copy_page", "Başlık ve URL'yi Kopyala", "Açık sayfanın başlığını ve URL'sini panoya kopyala."),
    ("robots", "robots.txt Aç", "Geçerli sitenin robots.txt dosyasını yeni sekmede aç."),
    ("sitemap", "sitemap.xml Aç", "Geçerli sitenin sitemap.xml konumunu yeni sekmede aç."),
    ("save_html", "Sayfanın HTML Çıktısını Kaydet", "Mevcut DOM'un HTML çıktısını dosyaya kaydet."),
    ("timer", "Dakikalı Hatırlatıcı", "Yerel bir hatırlatma zamanlayıcısı kur."),
    ("calculator", "Güvenli Hesap Makinesi", "Python kodu çalıştırmadan matematik ifadesi hesapla."),
    ("url_info", "Geçerli URL Bilgisi", "Protokol, alan adı, port ve sayfa başlığını gör."),
    ("db_report", "NOVA İndeks Raporu", "İndeks, kuyruk, hata, bağlantı ve DB boyutunu göster."),
]
# Add 12 entries so the tool center contains 52 usable items (40 original + 12 new).
_OSS22_FEATURES.extend(_NOVAOSV7_EXTRA_TOOLS)
_NOVAOSV7_BASE_DISPATCH = _oss22_dispatch
def _novaosv7_dispatch(browser, key):
    handlers = {
        "metadata": _novaosv7_page_metadata,
        "word_count": _novaosv7_word_count,
        "export_links": _novaosv7_export_links,
        "clean_url": _novaosv7_clean_url,
        "copy_page": _novaosv7_copy_page,
        "robots": _novaosv7_open_robots,
        "sitemap": _novaosv7_open_sitemap,
        "save_html": _novaosv7_save_html,
        "timer": _novaosv7_timer,
        "calculator": _novaosv7_calculator,
        "url_info": _novaosv7_url_info,
        "db_report": _novaosv7_database_report,
    }
    fn=handlers.get(key)
    if fn:
        try: fn(browser)
        except Exception as exc: QMessageBox.warning(browser,'NOVAOS V7 aracı',f'İşlem tamamlanamadı:\n{exc}')
    else:
        _NOVAOSV7_BASE_DISPATCH(browser,key)

_oss22_dispatch = _novaosv7_dispatch

# Rename and expand the existing feature center, while continuing to use its working handlers.
_NOVAOSV7_BASE_FEATURE_INIT = OSS22FeatureCenter.__init__
def _novaosv7_feature_init(self, browser):
    _NOVAOSV7_BASE_FEATURE_INIT(self,browser)
    self.setWindowTitle('NOVAOS V7 — 90 Araç (50 yeni)')
    for label in self.findChildren(QLabel):
        if '40 araç' in label.text():
            label.setText('52 işlevsel araç: web, NOVA, güvenlik, üretkenlik, belge araçları ve otomasyon.')
        if 'OSS BROWSER 2.2' in label.text():
            label.setText('NOVAOS V7 / ARAÇ MERKEZİ')
OSS22FeatureCenter.__init__ = _novaosv7_feature_init

# Link the small one-page dashboard buttons to real Qt actions.
_NOVAOSV7_BASE_NAV = BrowserPage.acceptNavigationRequest
def _novaosv7_nav(self, url, nav_type, is_main_frame):
    try:
        if is_main_frame and (url.host() or '').lower() == NOVA_SEARCH_HOST:
            path=(url.path() or '/').rstrip('/') or '/'
            params=parse_qs(url.query(),keep_blank_values=True)
            browser=self.browser
            if path == '/submit':
                query=_nova_clean(params.get('q',[''])[0])
                engine=params.get('engine',[NOVA_SEARCH_NAME])[0]
                if engine not in SEARCH_ENGINES: engine=NOVA_SEARCH_NAME
                browser.data.setdefault('settings',{})['search_engine']=engine
                browser.save()
                if not query: browser.go_home()
                elif engine == NOVA_SEARCH_NAME: QTimer.singleShot(0,lambda q=query:browser._nova_search(q,1))
                else:
                    template=SEARCH_ENGINES.get(engine)
                    if template:
                        QTimer.singleShot(0,lambda t=template,q=query:browser.current_view().setUrl(QUrl(t.format(quote_plus(q)))) if browser.current_view() else None)
                return False
            if path == '/tools':
                tool_key=params.get('key',[''])[0]
                if tool_key and tool_key in {item[0] for item in _OSS22_FEATURES}:
                    QTimer.singleShot(0,lambda k=tool_key:_oss22_dispatch(browser,k))
                else:
                    QTimer.singleShot(0,lambda b=browser:OSS22FeatureCenter(b).exec())
                return False
            if path in ('/admin','/manage'):
                QTimer.singleShot(0,lambda b=browser:OSSNovaAdminDialog(b).exec());return False
            if path == '/reindex':
                settings=browser.data.setdefault('settings',{});settings['nova_auto_resume']=True;browser.save()
                crawler=getattr(browser,'_nova_crawler',None)
                if crawler and crawler.running: browser.statusBar().showMessage('NOVA zaten tarıyor.',2200)
                else: _nova_start_crawler(browser,force=False)
                return False
            if path == '/history':
                QTimer.singleShot(0,lambda b=browser:HistoryDialog(b).exec());return False
            if path == '/bookmarks':
                QTimer.singleShot(0,lambda b=browser:BookmarkDialog(b).exec());return False
            if path == '/downloads':
                QTimer.singleShot(0,lambda b=browser:DownloadsDialog(b).exec());return False
            if path == '/notes':
                QTimer.singleShot(0,lambda b=browser:OSSNotesDialog(b).exec());return False
            if path == '/library':
                QTimer.singleShot(0,lambda b=browser:OSSOfflineLibraryDialog(b).exec());return False
            if path == '/settings':
                QTimer.singleShot(0,lambda b=browser:browser.open_settings());return False
            if path == '/home':
                QTimer.singleShot(0,lambda b=browser:b.go_home());return False
            if path == NOVA_SEARCH_PATH:
                query=_nova_clean(params.get('q',[''])[0]);page=int(params.get('p',['1'])[0] or 1)
                QTimer.singleShot(0,lambda q=query,p=page:browser._nova_search(q,p));return False
    except Exception as exc:
        try: self.browser.statusBar().showMessage('NOVAOS V7: '+str(exc)[:180],4000)
        except Exception: pass
        return False
    return _NOVAOSV7_BASE_NAV(self,url,nav_type,is_main_frame)
BrowserPage.acceptNavigationRequest = _novaosv7_nav

# Extra actions from Ctrl+K and from the tools menu.
def _novaosv7_add_menu(browser):
    try:
        button=getattr(browser,'tools_button',None)
        menu=button.menu() if button else None
        if menu is None or getattr(browser,'_novaosv7_menu_added',False): return
        browser._novaosv7_menu_added=True
        menu.addSeparator()
        menu.addAction('NOVAOS V7 — 90 Araç (50 yeni)',lambda b=browser:OSS22FeatureCenter(b).exec())
        menu.addAction('NOVAOS V7 — Dizin Yönetimi',lambda b=browser:OSSNovaAdminDialog(b).exec())
        menu.addAction('NOVAOS V7 — İndeks Raporu',lambda b=browser:_novaosv7_database_report(b))
    except Exception: pass

_NOVAOSV7_BASE_SETUP_UI = MainWindow.setup_ui
def _novaosv7_setup_ui(self,*args,**kwargs):
    _NOVAOSV7_BASE_SETUP_UI(self,*args,**kwargs)
    _novaosv7_add_menu(self)
MainWindow.setup_ui = _novaosv7_setup_ui
_NOVAOSV7_BASE_MAIN_INIT = MainWindow.__init__
def _novaosv7_main_init(self,*args,**kwargs):
    _NOVAOSV7_BASE_MAIN_INIT(self,*args,**kwargs)
    QTimer.singleShot(450,lambda b=self:_novaosv7_add_menu(b))
    try:
        self.setWindowTitle(f'{APP_NAME} v{APP_VERSION}')
        settings=self.data.setdefault('settings',{})
        settings.setdefault('nova_auto_resume',True)
        settings.setdefault('nova_workers',6)
        settings.setdefault('nova_session_limit',12000)
        settings.setdefault('nova_language_filter','turkish_first')
        self.save()
    except Exception: pass
MainWindow.__init__ = _novaosv7_main_init

# Refresh live counters without reloading the page (the search box won't lose text).
_NOVAOSV7_BASE_STATUS_UPDATE = _nova_status_update
def _novaosv7_status_update(browser):
    try: _NOVAOSV7_BASE_STATUS_UPDATE(browser)
    except Exception: pass
    try:
        tab=browser.current_tab()
        if not isinstance(tab,BrowserTab) or not getattr(tab,'is_home',False): return
        snap=_nova_status_snapshot(browser)
        data={"indexed":int(snap.get('indexed',0)),"queued":int(snap.get('queued',0)),"failed":int(snap.get('failed',0)),"workers":int(snap.get('workers',NOVA_WORKERS)),"running":bool(snap.get('running',False)),"fts":bool(snap.get('fts5',NOVA_FTS5_ENABLED))}
        script="(()=>{const d="+json.dumps(data)+";const set=(id,v)=>{const e=document.getElementById(id);if(e)e.textContent=v};set('statIndexed',d.indexed.toLocaleString('tr-TR'));set('statQueued',d.queued.toLocaleString('tr-TR'));set('statFailed',d.failed.toLocaleString('tr-TR'));set('statWorkers',d.workers);set('ftsState',d.fts?'Açık':'LIKE');set('statState',d.running?'Taranıyor':(d.queued?'Kuyrukta iş var':'Hazır'));set('stateText',d.running?'İndeksleniyor':(d.queued?'Kuyrukta iş var':'Dizin hazır'));})();"
        tab.view.page().runJavaScript(script)
    except Exception: pass
_nova_status_update = _novaosv7_status_update

# Queue more work automatically when a session reaches its safety limit, unless
# the user explicitly presses Stop. New pages are committed every batch and the
# existing live-search refresh checks the count every few seconds.
_NOVAOSV7_BASE_START = _nova_start_crawler
def _nova_start_crawler_novaosv7(browser, force=False, extra_seeds=None):
    try:
        s=browser.data.setdefault('settings',{})
        s.setdefault('nova_auto_resume',True)
    except Exception: pass
    return _NOVAOSV7_BASE_START(browser,force=force,extra_seeds=extra_seeds)
_nova_start_crawler = _nova_start_crawler_novaosv7
_NOVAOSV7_AUTORESTART_GUARD = threading.Lock()
def _novaosv7_auto_resume(browser):
    try:
        settings=browser.data.get('settings',{})
        if not settings.get('nova_auto_resume',True): return
        crawler=getattr(browser,'_nova_crawler',None)
        if not crawler or crawler.running: return
        snap=_nova_status_snapshot(browser)
        if int(snap.get('queued',0)) <= 0: return
        last=float(getattr(browser,'_novaosv7_last_restart',0))
        if time.monotonic()-last < 8: return
        browser._novaosv7_last_restart=time.monotonic()
        _nova_start_crawler(browser,force=False)
    except Exception: pass

_NOVAOSV7_BASE_ADMIN_STOP = OSSNovaAdminDialogV22.stop_crawl
_NOVAOSV7_BASE_ADMIN_START = OSSNovaAdminDialogV22.start_incremental
def _novaosv7_admin_stop(self):
    try:
        self.browser.data.setdefault('settings',{})['nova_auto_resume']=False
        self.browser.save()
    except Exception: pass
    return _NOVAOSV7_BASE_ADMIN_STOP(self)
def _novaosv7_admin_start(self):
    try:
        self.browser.data.setdefault('settings',{})['nova_auto_resume']=True
        self.browser.save()
    except Exception: pass
    return _NOVAOSV7_BASE_ADMIN_START(self)
OSSNovaAdminDialogV22.stop_crawl = _novaosv7_admin_stop
OSSNovaAdminDialogV22.start_incremental = _novaosv7_admin_start

# Combine live page counter refresh and controlled auto-resume.
def _novaosv7_status_update_with_resume(browser):
    _novaosv7_status_update(browser)
    _novaosv7_auto_resume(browser)
_nova_status_update = _novaosv7_status_update_with_resume

# App identity in Qt title, feature dialogs and status messages.
try:
    _oss22_version_key_original = _oss_version_key
except Exception:
    _oss22_version_key_original = None

APP_NAME = "NOVAOS V7"
APP_VERSION = "7.0.0"

# ---------------- NOVAOS V7: 38 additional tools (50 additions total) ----------------
def _novaosv7_eval_js(browser, script, callback):
    view = _novaosv7_active_view(browser)
    if not view:
        QMessageBox.information(browser, 'NOVAOS V7', 'Önce bir web sayfası aç.'); return
    view.page().runJavaScript(script, callback)

def _novaosv7_save_text_dialog(browser, text, suggested='novaosv7_export.txt', file_filter='Metin (*.txt)'):
    path, _ = QFileDialog.getSaveFileName(browser, 'Dışa aktar', suggested, file_filter)
    if not path: return
    try:
        Path(path).write_text(str(text or ''), encoding='utf-8-sig')
        browser.statusBar().showMessage('Dosya kaydedildi: '+path, 3500)
    except Exception as exc:
        QMessageBox.warning(browser, 'Dışa aktarma', str(exc))

def _novaosv7_page_text(browser):
    _novaosv7_eval_js(browser, "document.body ? document.body.innerText : ''", lambda text: _novaosv7_save_text_dialog(browser, text, 'sayfa_metni.txt'))

def _novaosv7_headings_export(browser):
    script = "JSON.stringify(Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6')).map((e)=>({level:e.tagName,text:(e.innerText||'').trim()})).filter(x=>x.text))"
    def done(raw):
        try: data=json.loads(raw or '[]'); text='\n'.join('#'*int(x['level'][1])+ ' '+x['text'] for x in data)
        except Exception: text=str(raw or '')
        if not text.strip(): text='Sayfada başlık bulunamadı.'
        _novaosv7_save_text_dialog(browser,text,'sayfa_basliklari.md','Markdown (*.md);;Metin (*.txt)')
    _novaosv7_eval_js(browser,script,done)

def _novaosv7_images_export(browser):
    script = "JSON.stringify(Array.from(document.images).map(i=>({src:i.currentSrc||i.src,alt:i.alt||'',width:i.naturalWidth||0,height:i.naturalHeight||0})).filter(x=>x.src).slice(0,3000))"
    def done(raw):
        try: rows=json.loads(raw or '[]')
        except Exception: rows=[]
        path,_=QFileDialog.getSaveFileName(browser,'Görsel listesini kaydet','sayfa_gorselleri.csv','CSV (*.csv);;JSON (*.json)')
        if not path:return
        try:
            if path.lower().endswith('.json'): Path(path).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
            else:
                with open(path,'w',newline='',encoding='utf-8-sig') as f:
                    w=_novaosv7_csv.DictWriter(f,fieldnames=['src','alt','width','height']);w.writeheader();w.writerows(rows)
            QMessageBox.information(browser,'Görsel listesi',f'{len(rows)} görsel kaydı yazıldı.')
        except Exception as exc:QMessageBox.warning(browser,'Görsel listesi',str(exc))
    _novaosv7_eval_js(browser,script,done)

def _novaosv7_copy_url(browser):
    url=_oss22_url_for_browser(browser)
    if not url:return
    QApplication.clipboard().setText(url);browser.statusBar().showMessage('URL panoya kopyalandı.',2200)

def _novaosv7_copy_domain(browser):
    host=urlparse(_oss22_url_for_browser(browser)).hostname or ''
    if not host:QMessageBox.information(browser,'Alan adı','Geçerli bir web alan adı yok.');return
    QApplication.clipboard().setText(host);browser.statusBar().showMessage('Alan adı panoya kopyalandı: '+host,2500)

def _novaosv7_translate_page(browser):
    url=_oss22_url_for_browser(browser)
    if not is_web_url(url):return
    browser.new_tab('https://translate.google.com/translate?sl=auto&tl=tr&u='+quote_plus(url))

def _novaosv7_search_selection_nova(browser):
    def done(text):
        text=str(text or '').strip()
        if not text:
            text,ok=QInputDialog.getText(browser,'Seçili metni NOVA’da ara','Arama metni:')
            if not ok:return
        browser._nova_search(text[:250],1)
    _novaosv7_eval_js(browser,'window.getSelection ? window.getSelection().toString() : ""',done)

def _novaosv7_search_selection_google(browser):
    def done(text):
        text=str(text or '').strip()
        if not text:
            text,ok=QInputDialog.getText(browser,'Seçili metni Google’da ara','Arama metni:')
            if not ok:return
        browser.new_tab('https://www.google.com/search?q='+quote_plus(text[:250]))
    _novaosv7_eval_js(browser,'window.getSelection ? window.getSelection().toString() : ""',done)

def _novaosv7_link_report(browser):
    script="JSON.stringify((()=>{const a=Array.from(document.querySelectorAll('a[href]'));const h=location.hostname;return {total:a.length,internal:a.filter(x=>{try{return new URL(x.href).hostname===h}catch(e){return false}}).length,external:a.filter(x=>{try{return /^https?:$/.test(new URL(x.href).protocol)&&new URL(x.href).hostname!==h}catch(e){return false}}).length,emptyText:a.filter(x=>!(x.innerText||x.getAttribute('aria-label')||'').trim()).length,noOpener:a.filter(x=>x.target==='_blank'&&!/\bnoopener\b/i.test(x.rel||'')).length,nonHttp:a.filter(x=>!/^https?:/i.test(x.href)).length}})())"
    def done(raw):
        try:d=json.loads(raw or '{}');text='\n'.join(f'{k}: {v}' for k,v in d.items())
        except Exception:text=str(raw)
        _novaosv7_notice(browser,'Bağlantı denetim raporu',text)
    _novaosv7_eval_js(browser,script,done)

def _novaosv7_image_report(browser):
    script="JSON.stringify((()=>{const a=Array.from(document.images);return {toplam:a.length,alternatifMetniEksik:a.filter(x=>!((x.alt||'').trim())).length,yuklenmeyen:a.filter(x=>!x.complete||x.naturalWidth===0).length,gecikmeli:a.filter(x=>x.loading==='lazy').length,genis:a.filter(x=>x.naturalWidth>1920).length}})())"
    def done(raw):
        try:d=json.loads(raw or '{}');text='\n'.join(f'{k}: {v}' for k,v in d.items())
        except Exception:text=str(raw)
        _novaosv7_notice(browser,'Görsel denetim raporu',text)
    _novaosv7_eval_js(browser,script,done)

def _novaosv7_page_language(browser):
    script="JSON.stringify({htmlLang:document.documentElement.lang||'(yok)',title:document.title,charset:document.characterSet,dir:document.documentElement.dir||'auto'})"
    def done(raw):
        try:d=json.loads(raw or '{}');text='\n'.join(f'{k}: {v}' for k,v in d.items())
        except Exception:text=str(raw)
        _novaosv7_notice(browser,'Sayfa dili ve karakter kodlaması',text)
    _novaosv7_eval_js(browser,script,done)

def _novaosv7_page_performance(browser):
    script="JSON.stringify((()=>{const n=performance.getEntriesByType('navigation')[0];return n?{loadMs:Math.round(n.loadEventEnd||n.duration),domReadyMs:Math.round(n.domContentLoadedEventEnd),responseMs:Math.round(n.responseEnd-n.requestStart),transferBytes:n.transferSize||0,resources:performance.getEntriesByType('resource').length}: {message:'Navigation Timing verisi yok'}})())"
    def done(raw):
        try:d=json.loads(raw or '{}');text='\n'.join(f'{k}: {v}' for k,v in d.items())
        except Exception:text=str(raw)
        _novaosv7_notice(browser,'Sayfa performans ölçümü',text+'\nNot: Sonuçlar Chromium Performance API verisidir; laboratuvar testi yerine geçmez.')
    _novaosv7_eval_js(browser,script,done)

def _novaosv7_scroll_top(browser):
    _novaosv7_eval_js(browser,'window.scrollTo({top:0,behavior:"smooth"})',lambda _=None:None)

def _novaosv7_scroll_bottom(browser):
    _novaosv7_eval_js(browser,'window.scrollTo({top:document.documentElement.scrollHeight,behavior:"smooth"})',lambda _=None:None)

def _novaosv7_zoom(browser, change):
    view=_novaosv7_active_view(browser)
    if not view:return
    try:
        current=float(view.zoomFactor())
        value=max(0.5,min(2.5,1.0 if change==0 else current+change))
        view.setZoomFactor(value);browser.statusBar().showMessage(f'Sayfa yakınlaştırma: %{round(value*100)}',2200)
    except Exception as exc:QMessageBox.warning(browser,'Yakınlaştırma',str(exc))
def _novaosv7_zoom_in(browser):_novaosv7_zoom(browser,0.1)
def _novaosv7_zoom_out(browser):_novaosv7_zoom(browser,-0.1)
def _novaosv7_zoom_reset(browser):_novaosv7_zoom(browser,0)

def _novaosv7_reopen_current(browser):
    url=_oss22_url_for_browser(browser)
    if is_web_url(url):browser.new_tab(url)

def _novaosv7_copy_markdown(browser):
    view=_novaosv7_active_view(browser)
    if not view:return
    title=(view.title() or 'Sayfa').replace(']','\\]')
    url=view.url().toString()
    QApplication.clipboard().setText(f'[{title}]({url})')
    browser.statusBar().showMessage('Markdown bağlantısı panoya kopyalandı.',2200)

def _novaosv7_reading_time(browser):
    script="JSON.stringify({words:((document.body&&document.body.innerText)||'').trim().split(/\\s+/).filter(Boolean).length})"
    def done(raw):
        try:words=int(json.loads(raw or '{}').get('words',0));mins=max(1,(words+199)//200);text=f'{words:,} kelime\nTahmini okuma süresi: {mins} dakika (200 kelime/dakika varsayımı).'
        except Exception:text=str(raw)
        _novaosv7_notice(browser,'Tahmini okuma süresi',text)
    _novaosv7_eval_js(browser,script,done)

def _novaosv7_selection_stats(browser):
    script="JSON.stringify((()=>{const t=window.getSelection?window.getSelection().toString():'';return {characters:t.length,words:(t.trim().match(/\\S+/g)||[]).length,preview:t.slice(0,400)}})())"
    def done(raw):
        try:d=json.loads(raw or '{}');text=f"Karakter: {d.get('characters',0)}\nKelime: {d.get('words',0)}\n\n{d.get('preview','')}"
        except Exception:text=str(raw)
        _novaosv7_notice(browser,'Seçili metin istatistikleri',text)
    _novaosv7_eval_js(browser,script,done)

def _novaosv7_extract_emails(browser):
    script="(document.body&&document.body.innerText)||''"
    def done(text):
        matches=sorted(set(re.findall(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',str(text or ''))))
        if not matches:matches=['Görünen sayfa metninde e-posta adresi bulunamadı.']
        _novaosv7_notice(browser,'Sayfadaki e-posta adresleri','\n'.join(matches[:300]))
    _novaosv7_eval_js(browser,script,done)

def _novaosv7_color_report(browser):
    script="JSON.stringify((()=>{const a=Array.from(document.querySelectorAll('body *')).slice(0,2500);const m={};for(const e of a){const s=getComputedStyle(e);for(const c of [s.color,s.backgroundColor]){if(c&&c!=='rgba(0, 0, 0, 0)')m[c]=(m[c]||0)+1}}return Object.entries(m).sort((a,b)=>b[1]-a[1]).slice(0,25).map(([color,count])=>({color,count}))})())"
    def done(raw):
        try:rows=json.loads(raw or '[]');text='\n'.join(f"{r['color']}: {r['count']} öğe" for r in rows)
        except Exception:text=str(raw)
        _novaosv7_notice(browser,'Sayfa renk paleti',text or 'Renk bilgisi bulunamadı.')
    _novaosv7_eval_js(browser,script,done)

def _novaosv7_open_https(browser):
    p=urlparse(_oss22_url_for_browser(browser))
    if p.scheme not in ('http','https') or not p.netloc:QMessageBox.information(browser,'HTTPS aç','Önce bir HTTP/HTTPS sayfası aç.');return
    target=p._replace(scheme='https').geturl()
    if p.scheme=='https':browser.statusBar().showMessage('Sayfa zaten HTTPS kullanıyor.',2200)
    else:browser.new_tab(target)

def _novaosv7_url_safety(browser):
    raw=_oss22_url_for_browser(browser);p=urlparse(raw);host=p.hostname or ''
    try:ascii_host=host.encode('idna').decode('ascii')
    except Exception:ascii_host='(çözümlenemedi)'
    warnings=[]
    if p.scheme!='https':warnings.append('Bağlantı HTTPS kullanmıyor.')
    if 'xn--' in ascii_host: warnings.append('Alan adı Punycode/IDN içeriyor; görünen karakterleri dikkatle incele.')
    if p.username or p.password:warnings.append('URL içinde kullanıcı bilgisi bulunuyor.')
    if host.count('-')>=3:warnings.append('Alan adında birden çok tire var; bu tek başına kötü niyet kanıtı değildir.')
    if not warnings:warnings.append('Bu temel kontrol belirgin bir işaret bulmadı; sayfanın güvenli olduğunu garanti etmez.')
    _novaosv7_notice(browser,'Temel URL güvenlik kontrolü',f'Adres: {raw}\nAlan adı: {host}\nASCII alan adı: {ascii_host}\n\n'+'\n'.join('• '+x for x in warnings))

def _novaosv7_save_page_note(browser):
    url=_oss22_url_for_browser(browser);view=_novaosv7_active_view(browser)
    if not url:return
    note,ok=QInputDialog.getMultiLineText(browser,'Sayfaya not ekle','Not:', '')
    if not ok:return
    notes=browser.data.setdefault('novaosv7_page_notes',[])
    notes.append({'url':url,'title':view.title() if view else url,'note':note,'created_at':datetime.now().isoformat(timespec='seconds')})
    browser.save();QMessageBox.information(browser,'Not kaydedildi','Not yerel tarayıcı verilerine kaydedildi.')

def _novaosv7_bookmark_current(browser):
    try:browser.add_bookmark()
    except Exception as exc:QMessageBox.warning(browser,'Yer imi',str(exc))

def _novaosv7_export_tabs(browser):
    items=[]
    try:
        for i in range(browser.tabs.count()):
            tab=browser.tabs.widget(i)
            if isinstance(tab,BrowserTab):items.append({'title':tab.view.title(),'url':tab.view.url().toString(),'pinned':bool(getattr(tab,'pinned',False))})
    except Exception as exc:QMessageBox.warning(browser,'Sekmeler dışa aktar',str(exc));return
    path,_=QFileDialog.getSaveFileName(browser,'Açık sekmeleri dışa aktar','novaosv7_sekmeler.json','JSON (*.json);;HTML (*.html)')
    if not path:return
    try:
        if path.lower().endswith('.html'):
            body=''.join('<li><a href="'+html.escape(x['url'],quote=True)+'">'+html.escape(x['title'] or x['url'])+'</a></li>' for x in items)
            Path(path).write_text('<!doctype html><meta charset="utf-8"><title>NOVAOS sekmeler</title><ul>'+body+'</ul>',encoding='utf-8')
        else:Path(path).write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')
        QMessageBox.information(browser,'Sekmeler dışa aktarıldı',f'{len(items)} sekme kaydedildi.')
    except Exception as exc:QMessageBox.warning(browser,'Sekmeler dışa aktar',str(exc))

def _novaosv7_export_history(browser):
    _novaosv7_save_text_dialog(browser,json.dumps(browser.data.get('history',[]),ensure_ascii=False,indent=2),'novaosv7_history.json','JSON (*.json);;Metin (*.txt)')

def _novaosv7_export_bookmarks(browser):
    _novaosv7_save_text_dialog(browser,json.dumps(browser.data.get('bookmarks',[]),ensure_ascii=False,indent=2),'novaosv7_bookmarks.json','JSON (*.json);;Metin (*.txt)')

def _novaosv7_copy_search_query(browser):
    tab=browser.current_tab();query=getattr(tab,'_nova_live_query','') if tab else ''
    if not query:
        query,ok=QInputDialog.getText(browser,'Arama metnini kopyala','Kopyalanacak arama metni:')
        if not ok:return
    QApplication.clipboard().setText(str(query));browser.statusBar().showMessage('Arama metni panoya kopyalandı.',2200)

def _novaosv7_search_title_nova(browser):
    view=_novaosv7_active_view(browser);query=view.title().strip() if view else ''
    if query:browser._nova_search(query,1)

def _novaosv7_search_title_google(browser):
    view=_novaosv7_active_view(browser);query=view.title().strip() if view else ''
    if query:browser.new_tab('https://www.google.com/search?q='+quote_plus(query))

def _novaosv7_open_favicon(browser):
    p=urlparse(_oss22_url_for_browser(browser))
    if p.scheme not in ('http','https') or not p.netloc:return
    browser.new_tab(p._replace(path='/favicon.ico',params='',query='',fragment='').geturl())

def _novaosv7_network_result(browser, title, payload):
    _novaosv7_notice(browser,title,payload)

class NOVAOSV7NetworkWorker(QThread):
    resultText=Signal(str,str)
    def __init__(self, mode, value, parent=None):
        super().__init__(parent);self.mode=mode;self.value=value
    def run(self):
        title='Ağ denetimi';lines=[]
        try:
            if self.mode=='dns':
                host=str(self.value).strip()
                infos=_novaosv7_socket.getaddrinfo(host,None,type=_novaosv7_socket.SOCK_STREAM)
                ips=sorted(set(x[4][0] for x in infos));title='DNS sorgusu';lines=[f'Host: {host}',*['IP: '+ip for ip in ips]]
            elif self.mode=='tls':
                p=urlparse(self.value);host=p.hostname or str(self.value);title='TLS sertifikası'
                ctx=_novaosv7_ssl.create_default_context()
                with _novaosv7_socket.create_connection((host,443),timeout=4) as sock:
                    with ctx.wrap_socket(sock,server_hostname=host) as tls:
                        cert=tls.getpeercert();exp=cert.get('notAfter','')
                        days=None
                        try:days=int((_novaosv7_ssl.cert_time_to_seconds(exp)-time.time())/86400)
                        except Exception:pass
                        lines=[f'Host: {host}',f'TLS: {tls.version()}',f'Sertifika sahibi: {cert.get("subject","")}',f'Bitiş: {exp}',f'Kalan gün: {days if days is not None else "bilinmiyor"}']
            elif self.mode=='http':
                title='HTTP yanıt kontrolü';url=str(self.value)
                req=urllib.request.Request(url,headers={'User-Agent':'NOVAOSV7/7.0'},method='HEAD')
                try:
                    with urllib.request.urlopen(req,timeout=4) as r:lines=[f'İstenen URL: {url}',f'Son URL: {r.geturl()}',f'Durum: {r.status}',f'Sunucu: {r.headers.get("Server","")}',f'İçerik türü: {r.headers.get("Content-Type","")}']
                except Exception as exc:
                    if isinstance(exc,urllib.error.HTTPError):lines=[f'URL: {url}',f'HTTP durumu: {exc.code}',f'Son URL: {exc.geturl()}']
                    else:lines=[f'URL: {url}',f'Hata: {exc}']
            elif self.mode=='links':
                title='Bağlantı yanıt denetimi';items=list(self.value)[:18]
                def check(url):
                    try:
                        req=urllib.request.Request(url,headers={'User-Agent':'NOVAOSV7/7.0'},method='HEAD')
                        with urllib.request.urlopen(req,timeout=3) as r:return (url,str(r.status),r.geturl())
                    except Exception as exc:
                        if isinstance(exc,urllib.error.HTTPError):return (url,str(exc.code),exc.geturl())
                        return (url,'HATA',str(exc)[:120])
                with ThreadPoolExecutor(max_workers=5,thread_name_prefix='NOVA-link-check') as pool:
                    results=list(pool.map(check,items))
                lines=[f'{status}  {url}'+(f' → {final}' if final and final!=url else '') for url,status,final in results]
                lines.insert(0,f'İlk {len(items)} bağlantı kontrol edildi; bazı sunucular HEAD isteğini reddedebilir.')
            else: lines=['Desteklenmeyen denetim.']
        except Exception as exc:lines=['Denetim başarısız: '+str(exc)]
        self.resultText.emit(title,'\n'.join(lines))

def _novaosv7_start_network_worker(browser, mode, value):
    worker=NOVAOSV7NetworkWorker(mode,value,browser)
    if not hasattr(browser,'_novaosv7_workers'):browser._novaosv7_workers=[]
    browser._novaosv7_workers.append(worker)
    worker.resultText.connect(lambda title,text:_novaosv7_network_result(browser,title,text))
    worker.finished.connect(lambda w=worker: browser._novaosv7_workers.remove(w) if w in getattr(browser,'_novaosv7_workers',[]) else None)
    worker.start()

def _novaosv7_site_tls(browser):
    p=urlparse(_oss22_url_for_browser(browser))
    if not p.hostname:QMessageBox.information(browser,'TLS','Geçerli alan adı yok.');return
    _novaosv7_start_network_worker(browser,'tls',p.geturl())

def _novaosv7_dns_lookup(browser):
    p=urlparse(_oss22_url_for_browser(browser));host=p.hostname
    if not host:
        host,ok=QInputDialog.getText(browser,'DNS sorgusu','Alan adı:')
        if not ok or not host.strip():return
    _novaosv7_start_network_worker(browser,'dns',host.strip())

def _novaosv7_http_check(browser):
    url=_oss22_url_for_browser(browser)
    if not is_web_url(url):QMessageBox.information(browser,'HTTP denetimi','Önce HTTP/HTTPS sayfası aç.');return
    _novaosv7_start_network_worker(browser,'http',url)

def _novaosv7_link_check(browser):
    script="JSON.stringify(Array.from(document.querySelectorAll('a[href]')).map(a=>a.href).filter(u=>/^https?:/i.test(u)).filter((u,i,a)=>a.indexOf(u)===i).slice(0,18))"
    def done(raw):
        try:urls=json.loads(raw or '[]')
        except Exception:urls=[]
        if not urls:QMessageBox.information(browser,'Bağlantı denetimi','HTTP bağlantısı bulunamadı.');return
        _novaosv7_start_network_worker(browser,'links',urls)
    _novaosv7_eval_js(browser,script,done)

_NOVAOSV7_MORE_TOOLS = [
 ('page_text','Görünen Sayfa Metnini Kaydet','Görünen metni TXT olarak dışa aktar.'),
 ('headings_export','Başlıkları Markdown Olarak Kaydet','H1-H6 başlıklarını Markdown listesine dönüştür.'),
 ('images_export','Görselleri CSV/JSON Olarak Dışa Aktar','Görsel URL, alt metin ve ölçülerini kaydet.'),
 ('copy_url','Geçerli URL’yi Kopyala','Adres çubuğundaki URL’yi panoya kopyala.'),
 ('copy_domain','Alan Adını Kopyala','Mevcut sayfanın host adını panoya kopyala.'),
 ('translate_page','Sayfayı Türkçeye Çevir','Mevcut URL’yi çeviri servisine gönder.'),
 ('search_selection_nova','Seçili Metni NOVA’da Ara','Seçimi yerel indeksinde ara.'),
 ('search_selection_google','Seçili Metni Google’da Ara','Seçilen metni Google’da aç.'),
 ('link_report','Bağlantı Kalitesi Raporu','İç/dış bağlantı, boş metin ve target güvenlik ipuçları.'),
 ('image_report','Görsel Kalitesi Raporu','Eksik alt metin, yüklenmeyen ve büyük görselleri say.'),
 ('page_language','Sayfa Dili ve Kodlaması','HTML lang, charset ve yön bilgisini göster.'),
 ('page_performance','Sayfa Performans Ölçümü','Navigation Timing ve kaynak sayısını göster.'),
 ('scroll_top','Sayfanın Başına Git','Sayfa kaydırmasını en üste getir.'),
 ('scroll_bottom','Sayfanın Sonuna Git','Sayfa kaydırmasını en alta götür.'),
 ('zoom_in','Yakınlaştır','Sayfa yakınlaştırmasını %10 artır.'),
 ('zoom_out','Uzaklaştır','Sayfa yakınlaştırmasını %10 azalt.'),
 ('zoom_reset','Yakınlaştırmayı Sıfırla','Sayfa yakınlaştırmasını %100 yap.'),
 ('reopen_current','Geçerli Sayfayı Yeni Sekmede Aç','Açık sayfanın URL’sini yeni sekmede aç.'),
 ('copy_markdown','Markdown Bağlantısı Kopyala','Sayfa başlığı ve URL’den Markdown bağlantısı oluştur.'),
 ('reading_time','Okuma Süresini Hesapla','Görünen metnin tahmini okuma süresini hesapla.'),
 ('selection_stats','Seçili Metin İstatistikleri','Seçili metnin karakter/kelime sayısını göster.'),
 ('extract_emails','Sayfa Metnindeki E-postaları Bul','Yalnızca görünür metinde eşleşen e-posta biçimlerini listeler.'),
 ('color_report','Sayfanın Renk Paleti','Sık kullanılan metin ve arka plan renklerini göster.'),
 ('open_https','HTTPS Adresini Aç','Mevcut HTTP sayfasını HTTPS ile yeni sekmede dene.'),
 ('url_safety','Temel URL Güvenlik Kontrolü','HTTPS ve IDN/Punycode gibi sinyalleri incele.'),
 ('save_page_note','Geçerli Sayfaya Not Ekle','Sayfa URL’siyle birlikte yerel not kaydet.'),
 ('bookmark_current','Geçerli Sayfayı Yer İmine Ekle','Tarayıcının mevcut yer imi işlevini çağır.'),
 ('export_tabs','Açık Sekmeleri Dışa Aktar','Sekme başlıklarını ve URL’lerini JSON/HTML dosyasına yaz.'),
 ('export_history','Geçmişi Dışa Aktar','Yerel tarayıcı geçmişini JSON/TXT dosyasına yaz.'),
 ('export_bookmarks','Yer İmlerini Dışa Aktar','Yer imlerini JSON/TXT dosyasına yaz.'),
 ('copy_search_query','Arama Metnini Kopyala','Son NOVA sorgusunu veya elle girilen metni kopyala.'),
 ('search_title_nova','Sayfa Başlığını NOVA’da Ara','Mevcut sayfa başlığını yerel indekste ara.'),
 ('search_title_google','Sayfa Başlığını Google’da Ara','Mevcut sayfa başlığını Google’da ara.'),
 ('open_favicon','Site Faviconunu Aç','Alan adının standart /favicon.ico adresini aç.'),
 ('site_tls','TLS Sertifikasını İncele','TLS sürümü ve sertifika bitiş tarihini arka planda sorgula.'),
 ('dns_lookup','DNS Kaydı Sorgula','Alan adının çözümlenen IP adreslerini arka planda göster.'),
 ('http_check','HTTP Yanıtını Kontrol Et','HTTP durum kodu, son URL ve içerik türünü kontrol et.'),
 ('link_check','Sayfa Bağlantılarını Denetle','İlk 18 benzersiz bağlantıya arka planda HEAD isteği gönder.'),
]
_OSS22_FEATURES.extend(_NOVAOSV7_MORE_TOOLS)
_NOVAOSV7_MORE_DISPATCH = _oss22_dispatch
_NOVAOSV7_MORE_HANDLERS = {
 'page_text':_novaosv7_page_text, 'headings_export':_novaosv7_headings_export, 'images_export':_novaosv7_images_export,
 'copy_url':_novaosv7_copy_url, 'copy_domain':_novaosv7_copy_domain, 'translate_page':_novaosv7_translate_page,
 'search_selection_nova':_novaosv7_search_selection_nova, 'search_selection_google':_novaosv7_search_selection_google,
 'link_report':_novaosv7_link_report, 'image_report':_novaosv7_image_report, 'page_language':_novaosv7_page_language,
 'page_performance':_novaosv7_page_performance, 'scroll_top':_novaosv7_scroll_top, 'scroll_bottom':_novaosv7_scroll_bottom,
 'zoom_in':_novaosv7_zoom_in, 'zoom_out':_novaosv7_zoom_out, 'zoom_reset':_novaosv7_zoom_reset,
 'reopen_current':_novaosv7_reopen_current, 'copy_markdown':_novaosv7_copy_markdown, 'reading_time':_novaosv7_reading_time,
 'selection_stats':_novaosv7_selection_stats, 'extract_emails':_novaosv7_extract_emails, 'color_report':_novaosv7_color_report,
 'open_https':_novaosv7_open_https, 'url_safety':_novaosv7_url_safety, 'save_page_note':_novaosv7_save_page_note,
 'bookmark_current':_novaosv7_bookmark_current, 'export_tabs':_novaosv7_export_tabs, 'export_history':_novaosv7_export_history,
 'export_bookmarks':_novaosv7_export_bookmarks, 'copy_search_query':_novaosv7_copy_search_query,
 'search_title_nova':_novaosv7_search_title_nova, 'search_title_google':_novaosv7_search_title_google, 'open_favicon':_novaosv7_open_favicon,
 'site_tls':_novaosv7_site_tls, 'dns_lookup':_novaosv7_dns_lookup, 'http_check':_novaosv7_http_check, 'link_check':_novaosv7_link_check,
}
def _novaosv7_dispatch_50(browser,key):
    fn=_NOVAOSV7_MORE_HANDLERS.get(key)
    if fn:
        try:fn(browser)
        except Exception as exc:QMessageBox.warning(browser,'NOVAOS V7 aracı',f'İşlem tamamlanamadı:\\n{exc}')
    else:_NOVAOSV7_MORE_DISPATCH(browser,key)
_oss22_dispatch=_novaosv7_dispatch_50

# Final names now state clearly that 50 tools were added to the existing 40.
_NOVAOSV7_OLD_FEATURE_INIT_50 = OSS22FeatureCenter.__init__
def _novaosv7_feature_init_90(self,browser):
    _NOVAOSV7_OLD_FEATURE_INIT_50(self,browser)
    self.setWindowTitle('NOVAOS V7 — 90 Araç (50 yeni)')
    for label in self.findChildren(QLabel):
        if '40 araç' in label.text() or '52 işlevsel araç' in label.text():
            label.setText('90 araç: 40 mevcut araç + 50 yeni araç. Web, NOVA, güvenlik, belge, medya ve ağ denetimleri.')
        if 'NOVAOS V7 / ARAÇ MERKEZİ' in label.text():
            label.setText('NOVAOS V7 / 90 ARAÇ · 50 YENİ')
OSS22FeatureCenter.__init__ = _novaosv7_feature_init_90

def _novaosv7_add_menu_90(browser):
    try:
        button=getattr(browser,'tools_button',None);menu=button.menu() if button else None
        if menu is None or getattr(browser,'_novaosv7_menu90_added',False):return
        browser._novaosv7_menu90_added=True
        menu.addSeparator()
        menu.addAction('NOVAOS V7 — 90 Araç (50 yeni)',lambda b=browser:OSS22FeatureCenter(b).exec())
        menu.addAction('NOVAOS V7 — İndeks / Performans Raporu',lambda b=browser:_novaosv7_database_report(b))
    except Exception:pass
_NOVAOSV7_PREV_SETUP_90=MainWindow.setup_ui
def _novaosv7_setup_ui_90(self,*args,**kwargs):
    _NOVAOSV7_PREV_SETUP_90(self,*args,**kwargs);_novaosv7_add_menu_90(self)
MainWindow.setup_ui=_novaosv7_setup_ui_90
_NOVAOSV7_PREV_INIT_90=MainWindow.__init__
def _novaosv7_init_90(self,*args,**kwargs):
    _NOVAOSV7_PREV_INIT_90(self,*args,**kwargs);QTimer.singleShot(650,lambda b=self:_novaosv7_add_menu_90(b))
MainWindow.__init__=_novaosv7_init_90

APP_NAME='NOVAOS V7'
APP_VERSION='7.0.0'


# ============================================================
# NOVAOS V7.1 — PyTube entegrasyonu + 50 ek işlev
# PyTube EXE kaynak kodu ayrı olduğu için güvenli biçimde kardeş işlem
# olarak açılır; EXE'nin kendisi bu kaynak dosyanın içine gömülmez.
# ============================================================
APP_NAME = "NOVAOS V7"
APP_VERSION = "7.1.0"

_NOVAOSV71_NEW_TOOLS = [
    ("pytub_launch", "PyTube Video İndirici", "Paketle gelen pytub.exe uygulamasını başlat."),
    ("qr_create", "QR Kod Oluşturucu", "Metin veya açık sayfa bağlantısı için QR PNG oluştur."),
    ("clipboard_tools", "Pano Metin Dönüştürücü", "Panoya kopyalanan metni dönüştür ve geri kopyala."),
    ("scratchpad", "Hızlı Not Defteri", "Yerel not dosyasını aç, düzenle ve kaydet."),
    ("open_download_dir", "İndirme Klasörünü Aç", "OSS indirme klasörünü Dosya Gezgini'nde aç."),
    ("open_app_dir", "NOVAOS Veri Klasörünü Aç", "Uygulamanın ayar ve indeks klasörünü aç."),
    ("export_session", "Açık Sekmeleri Oturum Olarak Kaydet", "Açık sekmeleri JSON oturumu olarak dışa aktar."),
    ("restore_session", "Oturum Dosyasını Geri Yükle", "JSON dosyasındaki sekmeleri aç."),
    ("bookmark_find", "Yer İmlerinde Ara", "Yer imlerinde ada veya URL'ye göre ara ve aç."),
    ("clear_domain_history", "Geçerli Alan Adının Geçmişini Sil", "Yalnızca açık sitenin geçmiş kayıtlarını kaldır."),
    ("link_domains", "Sayfadaki Alan Adlarını Özetle", "Sayfada bağlantı verilen alan adlarını say."),
    ("page_text_save", "Sayfa Metnini Dışa Aktar", "Görünen sayfa metnini TXT dosyasına kaydet."),
    ("tables_export_csv", "Sayfa Tablolarını CSV'ye Aktar", "HTML tablolarını CSV dosyasına çıkar."),
    ("regex_lab", "Regex Deneme Alanı", "Metin üzerinde düzenli ifade eşleşmelerini dene."),
    ("text_diff", "Metin Farkı Karşılaştırıcı", "İki metin arasındaki değişiklikleri bul."),
    ("base64_codec", "Base64 Kodlayıcı / Çözücü", "Metni Base64'e çevir veya Base64'ü çöz."),
    ("url_codec", "URL Kodlama Aracı", "URL metnini yüzde kodla veya geri çöz."),
    ("hash_tool", "SHA-256 / SHA-1 Hesaplayıcı", "Metin veya dosya için özet değer hesapla."),
    ("json_format", "JSON Biçimlendirici", "JSON doğrula, düzenle ve kaydet."),
    ("csv_preview", "CSV Önizleyici", "CSV dosyasının ilk satırlarını tablo olarak göster."),
    ("timestamp_convert", "Tarih / Unix Zaman Dönüştürücü", "Unix zamanını tarihe veya tarihi Unix'e çevir."),
    ("unit_convert", "Birim Dönüştürücü", "Uzunluk, ağırlık, veri boyutu ve sıcaklık dönüştür."),
    ("color_convert", "Renk Kodlayıcı", "HEX ve RGB renk gösterimlerini dönüştür."),
    ("text_sort_unique", "Metin Sırala ve Tekrarları Sil", "Satırları sırala ve yinelenenleri kaldır."),
    ("text_case", "Büyük / Küçük Harf Dönüştürücü", "Metni UPPER, lower, Title veya cümle biçimine çevir."),
    ("word_frequency", "Kelime Sıklığı Analizi", "Metinde en çok kullanılan kelimeleri listele."),
    ("markdown_preview", "Markdown Önizleyici", "Markdown metnini biçimlendirilmiş göster."),
    ("html_preview", "HTML Önizleyici", "HTML parçasını kısıtlı metin önizlemesinde göster."),
    ("selection_search", "Seçili Metni Aramada Aç", "Sayfada seçtiğin metni NOVA veya Google'da ara."),
    ("copy_canonical", "Canonical URL'yi Kopyala", "Sayfanın canonical URL değerini panoya kopyala."),
    ("screenshot_view", "Görünen Alanın Görüntüsünü Kaydet", "Mevcut sekmenin görünen alanını PNG kaydet."),
    ("page_pdf", "Sayfayı PDF Olarak Kaydet", "Mevcut sayfayı QtWebEngine yazdırma API'siyle PDF'ye aktar."),
    ("clear_cache", "Tarayıcı HTTP Önbelleğini Temizle", "Aktif profilin HTTP önbelleğini temizle."),
    ("clear_cookies", "Çerezleri Temizle", "Onaydan sonra tarayıcı profilinin çerezlerini sil."),
    ("search_engine_picker", "Varsayılan Arama Motorunu Değiştir", "Arama motorunu seç, kaydet ve ana sayfayı güncelle."),
    ("reader_toggle", "Sade Okuma Görünümünü Aç / Kapat", "Geçerli sayfadaki yazı ve arka planı sadeleştir."),
    ("image_toggle", "Geçerli Sekmede Görselleri Aç / Kapat", "Sekme görsellerinin otomatik yüklenmesini değiştir."),
    ("speech_read", "Sayfayı Sesli Oku", "Sayfa metnini tarayıcının konuşma senteziyle okumayı dene."),
    ("speech_stop", "Sesli Okumayı Durdur", "Geçerli sekmedeki konuşma sentezini durdur."),
    ("duplicate_tab", "Geçerli Sekmeyi Çoğalt", "Açık URL'yi yeni sekmede aç."),
    ("close_other_tabs", "Diğer Sekmeleri Kapat", "Aktif sekme dışındaki sekmeleri kapat."),
    ("mute_tab", "Sekme Sesini Aç / Kapat", "QtWebEngine destekliyorsa mevcut sekmenin sesini yönet."),
    ("save_tab_session", "Sekme Grubunu İsimle Kaydet", "Açık sekme URL'lerini yerel veriye bir oturum adıyla kaydet."),
    ("reopen_tab", "Son Kapatılan Sekmeyi Aç", "Son kapatılan sekmeyi geri getir."),
    ("copy_images_list", "Görsel Adreslerini Kopyala", "Sayfadaki görsel adreslerini TXT/clipboard olarak çıkar."),
    ("copy_headings", "Başlık Taslağını Kopyala", "H1-H6 başlık yapısını panoya al."),
    ("form_audit", "Form Güvenlik Özeti", "Form alanlarının tür ve adlarını göster; değerleri okumaz."),
    ("a11y_audit", "Erişilebilirlik Hızlı Denetimi", "Eksik alt metin ve adı olmayan düğmeleri say."),
    ("viewport_report", "Görüntü Alanı Raporu", "Pencere, ekran, DPR ve viewport ölçülerini göster."),
    ("open_system_browser", "Sayfayı Varsayılan Tarayıcıda Aç", "Geçerli sayfayı Windows varsayılan tarayıcısında aç."),
]
_OSS22_FEATURES.extend(_NOVAOSV71_NEW_TOOLS)


def _novav71_view(browser):
    try:
        return browser.current_view()
    except Exception:
        return None


def _novav71_js(browser, script, callback):
    view = _novav71_view(browser)
    if view is None:
        QMessageBox.information(browser, "NOVAOS V7.1", "Bu araç için önce bir web sayfası aç.")
        return
    view.page().runJavaScript(script, callback)


def _novav71_report(browser, title, text):
    try:
        _oss22_notice(browser, title, str(text))
    except Exception:
        QMessageBox.information(browser, title, str(text)[:4000])


def _novav71_save_text(browser, text, filename="novaos_export.txt", file_filter="Metin (*.txt)"):
    path, _ = QFileDialog.getSaveFileName(browser, "Dosyayı kaydet", str(DOWNLOAD_DIR / filename), file_filter)
    if not path:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(str(text), encoding="utf-8-sig")
        browser.statusBar().showMessage("Dosya kaydedildi: " + path, 3500)
    except Exception as exc:
        QMessageBox.warning(browser, "Kaydetme hatası", str(exc))


def _novav71_launch_pytub(browser):
    candidates = []
    try:
        here = Path(__file__).resolve().parent
        candidates.extend([here / "tools" / "pytub.exe", here / "pytub.exe"])
    except Exception:
        pass
    try:
        candidates.extend([Path(sys.executable).resolve().parent / "tools" / "pytub.exe", APP_DIR / "tools" / "pytub.exe"])
    except Exception:
        pass
    try:
        saved = browser.data.get("settings", {}).get("pytub_exe_path", "")
        if saved:
            candidates.insert(0, Path(saved))
    except Exception:
        pass
    exe = next((x for x in candidates if x.is_file()), None)
    if exe is None:
        selected, _ = QFileDialog.getOpenFileName(browser, "PyTube uygulamasını bul", str(Path.home()), "Windows uygulaması (*.exe)")
        if not selected:
            QMessageBox.information(browser, "PyTube", "PyTube dosyası bulunamadı. Paket içinde tools\\pytub.exe bulunmalı veya dosyayı seçmelisin.")
            return
        exe = Path(selected)
        try:
            browser.data.setdefault("settings", {})["pytub_exe_path"] = str(exe)
            browser.save()
        except Exception:
            pass
    try:
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True, creationflags=flags)
        browser.statusBar().showMessage("PyTube Video İndirici başlatıldı.", 3500)
    except Exception as exc:
        QMessageBox.critical(browser, "PyTube başlatılamadı", f"{exe}\n\n{exc}")


def _novav71_qr(browser):
    text, ok = QInputDialog.getText(browser, "QR Kod Oluşturucu", "Metin veya URL (boş bırakırsan açık sayfanın adresi kullanılır):")
    if not ok:
        return
    if not text.strip():
        text = _oss22_url_for_browser(browser)
    if not text:
        QMessageBox.information(browser, "QR", "Bir metin veya URL gir.")
        return
    try:
        import qrcode
        img = qrcode.make(text.strip())
        path, _ = QFileDialog.getSaveFileName(browser, "QR kodunu kaydet", str(DOWNLOAD_DIR / "novaos_qr.png"), "PNG (*.png)")
        if path:
            img.save(path)
            QMessageBox.information(browser, "QR kodu", "QR kodu kaydedildi:\n" + path)
    except ImportError:
        QMessageBox.warning(browser, "Eksik paket", "QR üretmek için şu paketi kur:\npython -m pip install \"qrcode[pil]\"")
    except Exception as exc:
        QMessageBox.warning(browser, "QR kodu", str(exc))


def _novav71_clipboard(browser):
    text = QApplication.clipboard().text()
    if not text:
        text, ok = QInputDialog.getMultiLineText(browser, "Pano Dönüştürücü", "Dönüştürülecek metin:")
        if not ok:
            return
    modes = ["Büyük harf", "Küçük harf", "Baş Harfler Büyük", "Satır boşluklarını temizle", "Satırları sırala", "Yinelenen satırları kaldır", "URL kodla", "URL çöz"]
    mode, ok = QInputDialog.getItem(browser, "Pano Dönüştürücü", "İşlem:", modes, 0, False)
    if not ok:
        return
    import urllib.parse
    if mode == modes[0]: out = text.upper()
    elif mode == modes[1]: out = text.lower()
    elif mode == modes[2]: out = text.title()
    elif mode == modes[3]: out = "\n".join(x.strip() for x in text.splitlines() if x.strip())
    elif mode == modes[4]: out = "\n".join(sorted(text.splitlines(), key=str.casefold))
    elif mode == modes[5]: out = "\n".join(dict.fromkeys(text.splitlines()))
    elif mode == modes[6]: out = urllib.parse.quote(text, safe="")
    else: out = urllib.parse.unquote(text)
    QApplication.clipboard().setText(out)
    _novav71_report(browser, "Pano Dönüştürücü", f"İşlem tamamlandı. {len(out)} karakter panoya kopyalandı.\n\n{out[:1800]}")


def _novav71_scratchpad(browser):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    path = APP_DIR / "quick_scratchpad.txt"
    dlg = QDialog(browser); dlg.setWindowTitle("NOVAOS Hızlı Not Defteri"); dlg.resize(700, 520)
    lay = QVBoxLayout(dlg); edit = QPlainTextEdit()
    try: edit.setPlainText(path.read_text(encoding="utf-8"))
    except Exception: pass
    lay.addWidget(edit, 1)
    row = QHBoxLayout(); save = QPushButton("Kaydet"); close = QPushButton("Kapat"); row.addWidget(save); row.addStretch(1); row.addWidget(close); lay.addLayout(row)
    def save_now():
        try: path.write_text(edit.toPlainText(), encoding="utf-8"); browser.statusBar().showMessage("Not kaydedildi.", 2500)
        except Exception as exc: QMessageBox.warning(dlg, "Not", str(exc))
    save.clicked.connect(save_now); close.clicked.connect(dlg.accept); dlg.exec()


def _novav71_open_folder(browser, path):
    try:
        path = Path(path); path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    except Exception as exc: QMessageBox.warning(browser, "Klasör açılamadı", str(exc))


def _novav71_export_session(browser):
    tabs=[]
    for i in range(browser.tabs.count()):
        w=browser.tabs.widget(i)
        v=getattr(w,"view",None)
        if v:
            url=v.url().toString()
            if url: tabs.append({"title":v.title() or "Sekme", "url":url, "private":bool(getattr(w,"private",False))})
    path,_=QFileDialog.getSaveFileName(browser,"Oturumu dışa aktar",str(DOWNLOAD_DIR/"novaos_session.json"),"JSON (*.json)")
    if path:
        try: Path(path).write_text(json.dumps({"app":"NOVAOS V7","created":datetime.now().isoformat(),"tabs":tabs},ensure_ascii=False,indent=2),encoding="utf-8")
        except Exception as exc: QMessageBox.warning(browser,"Oturum",str(exc))


def _novav71_restore_session(browser):
    path,_=QFileDialog.getOpenFileName(browser,"Oturum dosyası seç",str(DOWNLOAD_DIR),"JSON (*.json)")
    if not path:return
    try:
        payload=json.loads(Path(path).read_text(encoding="utf-8")); tabs=payload.get("tabs",[])
        if not isinstance(tabs,list): raise ValueError("JSON dosyasında tabs listesi yok.")
        if len(tabs)>80 and QMessageBox.question(browser,"Çok sekme",f"{len(tabs)} sekme açılacak. Devam edilsin mi?")!=QMessageBox.StandardButton.Yes:return
        opened=0
        for item in tabs[:200]:
            url=item.get("url","") if isinstance(item,dict) else str(item)
            if is_web_url(url): browser.new_tab(url); opened+=1
        QMessageBox.information(browser,"Oturum geri yüklendi",f"{opened} sekme açıldı.")
    except Exception as exc: QMessageBox.warning(browser,"Oturum dosyası",str(exc))


def _novav71_find_bookmark(browser):
    bookmarks=browser.data.get("bookmarks",[])
    if not bookmarks: QMessageBox.information(browser,"Yer imleri","Henüz yer imi yok."); return
    term,ok=QInputDialog.getText(browser,"Yer İmlerinde Ara","Ad veya URL:")
    if not ok:return
    rows=[]
    for item in bookmarks:
        if isinstance(item,dict):
            title=str(item.get("title",item.get("name","Yer imi"))); url=str(item.get("url",""))
        else: title=str(item); url=str(item)
        if term.casefold() in (title+" "+url).casefold(): rows.append((title,url))
    if not rows: QMessageBox.information(browser,"Yer imleri","Eşleşme bulunamadı."); return
    choice,ok=QInputDialog.getItem(browser,"Eşleşen yer imleri","Açılacak kayıt:",[f"{t} — {u}" for t,u in rows],0,False)
    if ok:
        idx=[f"{t} — {u}" for t,u in rows].index(choice); browser.new_tab(rows[idx][1])


def _novav71_clear_domain_history(browser):
    host=urlparse(_oss22_url_for_browser(browser)).hostname or ""
    if not host: QMessageBox.information(browser,"Geçmiş","Geçerli bir alan adı yok."); return
    if QMessageBox.question(browser,"Geçmişi sil",f"{host} alan adına ait geçmiş kayıtları silinsin mi?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
    hist=browser.data.get("history",[]); kept=[]; removed=0
    for item in hist:
        url=item.get("url","") if isinstance(item,dict) else str(item)
        if (urlparse(url).hostname or "").lower().removeprefix("www.")==host.lower().removeprefix("www."): removed+=1
        else: kept.append(item)
    browser.data["history"]=kept; browser.save(); QMessageBox.information(browser,"Geçmiş",f"{removed} kayıt silindi.")


def _novav71_link_domains(browser):
    script="JSON.stringify(Array.from(document.querySelectorAll('a[href]')).map(a=>{try{return new URL(a.href).hostname}catch(e){return ''}}).filter(Boolean).reduce((o,h)=>(o[h]=(o[h]||0)+1,o),{}))"
    def done(raw):
        try: data=json.loads(raw or "{}"); text="\n".join(f"{k}: {v}" for k,v in sorted(data.items(),key=lambda x:-x[1])) or "Bağlantı yok."
        except Exception:text=str(raw)
        _novav71_report(browser,"Alan Adı Özeti",text)
    _novav71_js(browser,script,done)


def _novav71_page_text_save(browser):
    _novav71_js(browser,"document.body ? document.body.innerText : ''",lambda text:_novav71_save_text(browser,text or "","sayfa_metni.txt"))


def _novav71_tables_csv(browser):
    script="JSON.stringify(Array.from(document.querySelectorAll('table')).map(t=>Array.from(t.querySelectorAll('tr')).map(tr=>Array.from(tr.querySelectorAll('th,td')).map(c=>(c.innerText||'').trim()))))"
    def done(raw):
        try: tables=json.loads(raw or "[]")
        except Exception: tables=[]
        if not tables: QMessageBox.information(browser,"CSV aktarımı","Sayfada tablo bulunamadı."); return
        import csv
        path,_=QFileDialog.getSaveFileName(browser,"Tabloları CSV kaydet",str(DOWNLOAD_DIR/"sayfa_tablolari.csv"),"CSV (*.csv)")
        if not path:return
        try:
            with open(path,"w",newline="",encoding="utf-8-sig") as f:
                writer=csv.writer(f)
                for i,table in enumerate(tables):
                    if i: writer.writerow([])
                    writer.writerows(table)
            QMessageBox.information(browser,"CSV aktarımı",f"{len(tables)} tablo kaydedildi.\n{path}")
        except Exception as exc: QMessageBox.warning(browser,"CSV aktarımı",str(exc))
    _novav71_js(browser,script,done)


def _novav71_regex(browser):
    pattern,ok=QInputDialog.getText(browser,"Regex Deneme Alanı","Python düzenli ifade deseni:")
    if not ok:return
    text,ok=QInputDialog.getMultiLineText(browser,"Regex Deneme Alanı","Denenecek metin:")
    if not ok:return
    try:
        matches=list(re.finditer(pattern,text)); lines=[]
        for m in matches[:200]: lines.append(f"{m.start()}–{m.end()}: {m.group(0)!r}")
        _novav71_report(browser,"Regex sonuçları",f"Eşleşme: {len(matches)}\n\n"+("\n".join(lines) or "Eşleşme bulunamadı."))
    except re.error as exc: QMessageBox.warning(browser,"Regex hatası",str(exc))


def _novav71_text_diff(browser):
    import difflib
    dlg=QDialog(browser);dlg.setWindowTitle("Metin Farkı Karşılaştırıcı");dlg.resize(900,680);root=QVBoxLayout(dlg)
    split=QSplitter(Qt.Orientation.Horizontal); a=QPlainTextEdit(); b=QPlainTextEdit(); a.setPlaceholderText("Eski metin…");b.setPlaceholderText("Yeni metin…");split.addWidget(a);split.addWidget(b);root.addWidget(split,1)
    result=QPlainTextEdit();result.setReadOnly(True);result.setPlaceholderText("Fark raporu");root.addWidget(result,1)
    row=QHBoxLayout();run=QPushButton("Karşılaştır");save=QPushButton("Raporu Kaydet");close=QPushButton("Kapat");row.addWidget(run);row.addWidget(save);row.addStretch(1);row.addWidget(close);root.addLayout(row)
    run.clicked.connect(lambda:result.setPlainText("".join(difflib.unified_diff(a.toPlainText().splitlines(True),b.toPlainText().splitlines(True),fromfile="eski",tofile="yeni")) or "Değişiklik bulunmadı."))
    save.clicked.connect(lambda:_novav71_save_text(browser,result.toPlainText(),"metin_farki.diff","Metin farkı (*.diff *.txt)"));close.clicked.connect(dlg.accept);dlg.exec()


def _novav71_base64(browser):
    import base64
    text,ok=QInputDialog.getMultiLineText(browser,"Base64 Aracı","Metin veya Base64 dizisi:")
    if not ok:return
    mode,ok=QInputDialog.getItem(browser,"Base64 Aracı","İşlem:",["Metni Base64'e kodla","Base64'ü UTF-8 olarak çöz"],0,False)
    if not ok:return
    try: out=base64.b64encode(text.encode("utf-8")).decode("ascii") if mode.startswith("Metni") else base64.b64decode(text.encode("ascii"),validate=True).decode("utf-8")
    except Exception as exc: QMessageBox.warning(browser,"Base64",str(exc));return
    QApplication.clipboard().setText(out);_novav71_report(browser,"Base64 sonucu","Sonuç panoya kopyalandı:\n\n"+out)


def _novav71_url_codec(browser):
    from urllib.parse import quote, unquote
    text,ok=QInputDialog.getText(browser,"URL Kodlayıcı","URL veya metin:")
    if not ok:return
    mode,ok=QInputDialog.getItem(browser,"URL Kodlayıcı","İşlem:",["Kodla","Çöz"],0,False)
    if not ok:return
    out=quote(text,safe=":/?#[]@!$&'()*+,;=%") if mode=="Kodla" else unquote(text)
    QApplication.clipboard().setText(out);_novav71_report(browser,"URL sonucu",out)


def _novav71_hash(browser):
    mode,ok=QInputDialog.getItem(browser,"Özet Hesaplayıcı","Girdi türü:",["Metin","Dosya"],0,False)
    if not ok:return
    if mode=="Dosya":
        path,_=QFileDialog.getOpenFileName(browser,"Özet alınacak dosyayı seç")
        if not path:return
        sha=hashlib.sha256()
        try:
            with open(path,"rb") as f:
                for chunk in iter(lambda:f.read(1024*1024),b""):sha.update(chunk)
            _novav71_report(browser,"SHA-256",f"Dosya: {path}\nSHA-256: {sha.hexdigest()}")
        except Exception as exc: QMessageBox.warning(browser,"Hash",str(exc))
    else:
        text,ok=QInputDialog.getMultiLineText(browser,"Özet Hesaplayıcı","Metin:")
        if ok:_novav71_report(browser,"SHA-256",hashlib.sha256(text.encode("utf-8")).hexdigest())


def _novav71_json_format(browser):
    path,_=QFileDialog.getOpenFileName(browser,"JSON seç (iptal ederek metin girebilirsin)",str(Path.home()),"JSON (*.json);;Tüm dosyalar (*.*)")
    if path:
        try: raw=Path(path).read_text(encoding="utf-8-sig")
        except Exception as exc: QMessageBox.warning(browser,"JSON",str(exc));return
    else:
        raw,ok=QInputDialog.getMultiLineText(browser,"JSON Biçimlendirici","JSON metni:")
        if not ok:return
    try: formatted=json.dumps(json.loads(raw),ensure_ascii=False,indent=2)
    except Exception as exc: QMessageBox.warning(browser,"Geçersiz JSON",str(exc));return
    dlg=QDialog(browser);dlg.setWindowTitle("JSON Biçimlendirici");dlg.resize(800,600);lay=QVBoxLayout(dlg);edit=QPlainTextEdit();edit.setPlainText(formatted);lay.addWidget(edit,1)
    row=QHBoxLayout();copy=QPushButton("Kopyala");save=QPushButton("Kaydet");close=QPushButton("Kapat");row.addWidget(copy);row.addWidget(save);row.addStretch(1);row.addWidget(close);lay.addLayout(row)
    copy.clicked.connect(lambda:QApplication.clipboard().setText(edit.toPlainText()));save.clicked.connect(lambda:_novav71_save_text(browser,edit.toPlainText(),"formatted.json","JSON (*.json)"));close.clicked.connect(dlg.accept);dlg.exec()


def _novav71_csv_preview(browser):
    import csv
    path,_=QFileDialog.getOpenFileName(browser,"CSV seç",str(Path.home()),"CSV (*.csv *.tsv);;Tüm dosyalar (*.*)")
    if not path:return
    try:
        with open(path,"r",encoding="utf-8-sig",newline="") as f: rows=list(csv.reader(f))[:81]
        _novav71_report(browser,"CSV Önizleyici",f"Dosya: {path}\nGösterilen satır: {len(rows)} (en fazla 80 veri satırı + başlık)\n\n"+"\n".join(" | ".join(c) for c in rows))
    except Exception as exc: QMessageBox.warning(browser,"CSV",str(exc))


def _novav71_timestamp(browser):
    raw,ok=QInputDialog.getText(browser,"Unix Zaman / Tarih","Unix saniyesi veya ISO tarih (örn. 2026-10-14T12:30:00):")
    if not ok or not raw.strip():return
    try:
        if re.fullmatch(r"-?\d+(\.\d+)?",raw.strip()):
            dt=datetime.fromtimestamp(float(raw.strip())).astimezone()
        else:
            dt=datetime.fromisoformat(raw.strip()).astimezone()
        _novav71_report(browser,"Tarih dönüştürücü",f"Yerel tarih: {dt.isoformat()}\nUnix saniyesi: {dt.timestamp():.3f}\nUTC: {dt.astimezone(__import__('datetime').timezone.utc).isoformat()}")
    except Exception as exc: QMessageBox.warning(browser,"Tarih formatı",str(exc))


def _novav71_units(browser):
    raw,ok=QInputDialog.getText(browser,"Birim Dönüştürücü","Değer ve birim (örn. 10 km, 500 MB, 25 C):")
    if not ok:return
    m=re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*([a-zA-Z]+)\s*",raw)
    if not m: QMessageBox.information(browser,"Birim Dönüştürücü","Örnek: 10 km, 3 mi, 500 MB, 25 C, 32 F");return
    v=float(m.group(1));u=m.group(2).lower();out=None
    factor={"m":1,"km":1000,"cm":.01,"mm":.001,"mi":1609.344,"mile":1609.344,"ft":.3048,"in":.0254}
    if u in factor:out=f"Metre: {v*factor[u]:.6g}\nKilometre: {v*factor[u]/1000:.6g}\nMil: {v*factor[u]/1609.344:.6g}"
    elif u in {"b","kb","mb","gb","tb"}:
        powers={"b":0,"kb":1,"mb":2,"gb":3,"tb":4}; bytesv=v*(1000**powers[u]);out=f"Bayt (ondalık): {bytesv:.0f}\nMiB: {bytesv/(1024**2):.6g}\nGiB: {bytesv/(1024**3):.6g}"
    elif u in {"c","°c"}:out=f"Fahrenheit: {v*9/5+32:.6g}\nKelvin: {v+273.15:.6g}"
    elif u in {"f","°f"}:out=f"Celsius: {(v-32)*5/9:.6g}\nKelvin: {(v-32)*5/9+273.15:.6g}"
    elif u in {"kg","g","mg","lb"}:
        kg=v*{"kg":1,"g":.001,"mg":.000001,"lb":.45359237}[u];out=f"Kilogram: {kg:.6g}\nGram: {kg*1000:.6g}\nPound: {kg/.45359237:.6g}"
    else:out="Desteklenen birimler: m, km, cm, mm, mi, ft, in, B, KB, MB, GB, TB, C, F, kg, g, mg, lb"
    _novav71_report(browser,"Birim sonucu",out)


def _novav71_color(browser):
    raw,ok=QInputDialog.getText(browser,"Renk Dönüştürücü","HEX (#RRGGBB) veya RGB (rgb(12,34,56)):")
    if not ok:return
    try:
        if raw.strip().startswith("#"):
            h=raw.strip().lstrip("#")
            if len(h)==3:h="".join(c*2 for c in h)
            if len(h)!=6:raise ValueError("HEX formatı #RRGGBB olmalı")
            r,g,b=(int(h[i:i+2],16) for i in (0,2,4))
        else:
            nums=[int(x) for x in re.findall(r"\d+",raw)]
            if len(nums)!=3 or any(x<0 or x>255 for x in nums):raise ValueError("RGB üç adet 0–255 sayı içermeli")
            r,g,b=nums
        _novav71_report(browser,"Renk sonucu",f"HEX: #{r:02X}{g:02X}{b:02X}\nRGB: rgb({r}, {g}, {b})\nHSL: {__import__('colorsys').rgb_to_hls(r/255,g/255,b/255)}")
    except Exception as exc:QMessageBox.warning(browser,"Renk formatı",str(exc))


def _novav71_sort_unique(browser):
    text,ok=QInputDialog.getMultiLineText(browser,"Metin Sırala","Satırları gir:")
    if not ok:return
    out="\n".join(sorted(set(x.strip() for x in text.splitlines() if x.strip()),key=str.casefold))
    QApplication.clipboard().setText(out);_novav71_report(browser,"Metin işlendi",f"{len(out.splitlines())} benzersiz satır panoya kopyalandı.\n\n{out[:2000]}")


def _novav71_case(browser):
    text,ok=QInputDialog.getMultiLineText(browser,"Metin Dönüştürücü","Metin:")
    if not ok:return
    mode,ok=QInputDialog.getItem(browser,"Metin Dönüştürücü","Biçim:",["UPPERCASE","lowercase","Title Case","Cümle biçimi"],0,False)
    if not ok:return
    out=text.upper() if mode=="UPPERCASE" else text.lower() if mode=="lowercase" else text.title() if mode=="Title Case" else (text[:1].upper()+text[1:].lower())
    QApplication.clipboard().setText(out);_novav71_report(browser,"Dönüştürülmüş metin","Sonuç panoya kopyalandı:\n\n"+out[:2500])


def _novav71_word_frequency(browser):
    text,ok=QInputDialog.getMultiLineText(browser,"Kelime Sıklığı","Metni gir:")
    if not ok:return
    words=re.findall(r"[\wğüşöçıİĞÜŞÖÇ'-]+",text.casefold())
    from collections import Counter
    counts=Counter(words)
    _novav71_report(browser,"Kelime Sıklığı",f"Toplam kelime: {len(words)}\nBenzersiz: {len(counts)}\n\n"+"\n".join(f"{w}: {c}" for w,c in counts.most_common(50)))


def _novav71_markdown(browser):
    text,ok=QInputDialog.getMultiLineText(browser,"Markdown Önizleyici","Markdown içeriği:")
    if not ok:return
    dlg=QDialog(browser);dlg.setWindowTitle("Markdown Önizleme");dlg.resize(800,650);lay=QVBoxLayout(dlg);view=QTextBrowser();view.setOpenExternalLinks(False)
    try:view.setMarkdown(text)
    except Exception:view.setPlainText(text)
    lay.addWidget(view,1);close=QPushButton("Kapat");close.clicked.connect(dlg.accept);lay.addWidget(close);dlg.exec()


def _novav71_html_preview(browser):
    text,ok=QInputDialog.getMultiLineText(browser,"HTML Önizleyici","HTML parçası:","<!doctype html><html><body><h1>Merhaba</h1><p>Önizleme</p></body></html>")
    if not ok:return
    # QTextBrowser doesn't execute page scripts; this is a text/document preview, not a web runtime.
    dlg=QDialog(browser);dlg.setWindowTitle("HTML Belge Önizlemesi");dlg.resize(850,650);lay=QVBoxLayout(dlg);view=QTextBrowser();view.setOpenExternalLinks(False);view.setHtml(text);lay.addWidget(view,1);close=QPushButton("Kapat");close.clicked.connect(dlg.accept);lay.addWidget(close);dlg.exec()


def _novav71_selection_search(browser):
    _novav71_js(browser,"(window.getSelection?String(window.getSelection()):'')",lambda text:_novav71_selection_got(browser,text))

def _novav71_selection_got(browser,text):
    text=(text or "").strip()
    if not text:text,ok=QInputDialog.getText(browser,"Seçili Metni Ara","Aranacak metin:")
    else:ok=True
    if not ok or not text.strip():return
    engine,ok=QInputDialog.getItem(browser,"Arama hedefi","Motor:",["NOVA Search","Google","Bing","DuckDuckGo"],0,False)
    if not ok:return
    if engine=="NOVA Search":browser._nova_search(text,1)
    else:
        template=SEARCH_ENGINES.get(engine,"https://www.google.com/search?q={}")
        if template:browser.new_tab(template.format(__import__('urllib.parse').parse.quote_plus(text)))


def _novav71_canonical(browser):
    _novav71_js(browser,"(document.querySelector('link[rel=canonical]')||{}).href||location.href",lambda u:(QApplication.clipboard().setText(str(u or "")),browser.statusBar().showMessage("Canonical URL panoya kopyalandı.",2500)))


def _novav71_screenshot(browser):
    view=_novav71_view(browser)
    if not view:return
    path,_=QFileDialog.getSaveFileName(browser,"Görünen alanı kaydet",str(DOWNLOAD_DIR/"novaos_screenshot.png"),"PNG (*.png);;JPEG (*.jpg *.jpeg)")
    if not path:return
    try:
        if not view.grab().save(path):raise RuntimeError("Görüntü dosyası kaydedilemedi.")
        browser.statusBar().showMessage("Ekran görüntüsü kaydedildi.",3000)
    except Exception as exc:QMessageBox.warning(browser,"Ekran görüntüsü",str(exc))


def _novav71_page_pdf(browser):
    view=_novav71_view(browser)
    if not view:return
    path,_=QFileDialog.getSaveFileName(browser,"Sayfayı PDF kaydet",str(DOWNLOAD_DIR/"web_sayfasi.pdf"),"PDF (*.pdf)")
    if not path:return
    try:
        view.page().printToPdf(path)
        browser.statusBar().showMessage("PDF oluşturma başlatıldı: "+path,3500)
    except Exception as exc:QMessageBox.warning(browser,"PDF",str(exc))


def _novav71_clear_cache(browser):
    view=_novav71_view(browser)
    if not view:return
    if QMessageBox.question(browser,"HTTP önbelleği", "Aktif tarayıcı profilinin HTTP önbelleği temizlensin mi?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
    try:view.page().profile().clearHttpCache();QMessageBox.information(browser,"Önbellek","HTTP önbelleği temizleme isteği gönderildi.")
    except Exception as exc:QMessageBox.warning(browser,"Önbellek",str(exc))


def _novav71_clear_cookies(browser):
    view=_novav71_view(browser)
    if not view:return
    if QMessageBox.question(browser,"Çerezleri sil","Aktif profilin tüm çerezleri silinecek ve oturumların kapanabilir. Devam edilsin mi?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
    try:view.page().profile().cookieStore().deleteAllCookies();QMessageBox.information(browser,"Çerezler","Tüm çerezleri silme isteği gönderildi.")
    except Exception as exc:QMessageBox.warning(browser,"Çerezler",str(exc))


def _novav71_engine(browser):
    names=list(SEARCH_ENGINES.keys())
    current=browser.data.get("settings",{}).get("search_engine",NOVA_SEARCH_NAME)
    choice,ok=QInputDialog.getItem(browser,"Varsayılan Arama Motoru","Motor:",names,max(0,names.index(current) if current in names else 0),False)
    if not ok:return
    browser.data.setdefault("settings",{})["search_engine"]=choice;browser.save();browser.go_home()
    browser.statusBar().showMessage("Arama motoru kaydedildi: "+choice,3000)


def _novav71_reader(browser):
    script="""(()=>{const id='__novaosv71_reader_style';let e=document.getElementById(id);if(e){e.remove();return 'Sade görünüm kapatıldı';}e=document.createElement('style');e.id=id;e.textContent='html body{max-width:900px!important;margin:30px auto!important;padding:35px!important;background:#faf7ef!important;color:#202020!important;font:20px/1.8 Georgia,serif!important}body *{background-color:transparent!important;color:#202020!important;box-shadow:none!important;text-shadow:none!important}img,video,svg{max-width:100%!important}';document.documentElement.appendChild(e);return 'Sade görünüm açıldı';})()"""
    _novav71_js(browser,script,lambda msg:browser.statusBar().showMessage(str(msg or "Okuma görünümü güncellendi."),2500))


def _novav71_images_toggle(browser):
    view=_novav71_view(browser)
    if not view:return
    settings=view.settings();attr=QWebEngineSettings.WebAttribute.AutoLoadImages
    try:
        enabled=settings.testAttribute(attr);settings.setAttribute(attr,not enabled)
        browser.statusBar().showMessage("Görsel yükleme: "+("açık" if not enabled else "kapalı")+" (sayfayı yenilemen gerekebilir).",3500)
    except Exception as exc:QMessageBox.warning(browser,"Görseller",str(exc))


def _novav71_speech(browser):
    _novav71_js(browser,"(()=>{const t=(document.body&&document.body.innerText||'').slice(0,12000);if(!t)return 'Sayfa metni yok';if(!window.speechSynthesis)return 'Sesli okuma desteklenmiyor';speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(t);u.lang='tr-TR';speechSynthesis.speak(u);return 'Sesli okuma başlatıldı';})()",lambda msg:browser.statusBar().showMessage(str(msg or "Sesli okuma isteği gönderildi."),3500))


def _novav71_speech_stop(browser):
    _novav71_js(browser,"(()=>{if(window.speechSynthesis){speechSynthesis.cancel();return 'Sesli okuma durduruldu'}return 'Sesli okuma desteklenmiyor'})()",lambda msg:browser.statusBar().showMessage(str(msg or "Sesli okuma durduruldu."),2500))


def _novav71_duplicate(browser):
    tab=browser.current_tab()
    if tab and tab.view.url().toString():browser.new_tab(tab.view.url().toString(),private=bool(getattr(tab,"private",False)))


def _novav71_close_others(browser):
    active=browser.current_tab()
    if active is None:return
    for i in range(browser.tabs.count()-1,-1,-1):
        w=browser.tabs.widget(i)
        if w is not active:browser.close_tab(i)
    idx=browser.tabs.indexOf(active)
    if idx>=0:browser.tabs.setCurrentIndex(idx)


def _novav71_mute(browser):
    view=_novav71_view(browser)
    if not view:return
    page=view.page()
    try:
        state=bool(page.isAudioMuted());page.setAudioMuted(not state)
        browser.statusBar().showMessage("Sekme sesi "+("kapatıldı" if not state else "açıldı"),2500)
    except Exception:QMessageBox.information(browser,"Sekme sesi","Bu QtWebEngine sürümü sayfa sesini programatik kontrol etmeyi desteklemiyor.")


def _novav71_save_tab_session(browser):
    name,ok=QInputDialog.getText(browser,"Sekme Grubunu Kaydet","Oturum adı:")
    if not ok or not name.strip():return
    urls=[]
    for i in range(browser.tabs.count()):
        w=browser.tabs.widget(i);v=getattr(w,"view",None)
        if v and v.url().toString():urls.append({"title":v.title() or "Sekme","url":v.url().toString()})
    sessions=browser.data.setdefault("saved_tab_sessions",[]);sessions.append({"name":name.strip(),"saved":datetime.now().isoformat(timespec="seconds"),"tabs":urls});browser.data["saved_tab_sessions"]=sessions[-100:];browser.save()
    QMessageBox.information(browser,"Oturum kaydedildi",f"{len(urls)} sekme '{name.strip()}' adıyla kaydedildi.")


def _novav71_reopen_tab(browser):
    closed=getattr(browser,"closed_tabs",[])
    if not closed:QMessageBox.information(browser,"Sekmeyi geri aç","Kayıtlı kapalı sekme yok.");return
    item=closed.pop(0)
    try:url,private=item
    except Exception:url,private=str(item),False
    if url:browser.new_tab(url,private=bool(private))


def _novav71_copy_images(browser):
    script="JSON.stringify(Array.from(document.images).map(i=>({src:i.currentSrc||i.src,alt:i.alt||'',width:i.naturalWidth,height:i.naturalHeight})).filter(x=>x.src))"
    def done(raw):
        try:rows=json.loads(raw or "[]")
        except Exception:rows=[]
        out="\n".join(f"{r['src']}\t{r['width']}x{r['height']}\t{r['alt']}" for r in rows)
        if not out:QMessageBox.information(browser,"Görseller","Görsel bulunamadı.");return
        QApplication.clipboard().setText(out);_novav71_report(browser,"Görsel adresleri",f"{len(rows)} kayıt panoya kopyalandı.\n\n{out[:4000]}")
    _novav71_js(browser,script,done)


def _novav71_copy_headings(browser):
    script="JSON.stringify(Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6')).map(e=>'#'.repeat(Number(e.tagName.slice(1)))+' '+(e.innerText||'').trim()).filter(Boolean))"
    def done(raw):
        try:out="\n".join(json.loads(raw or "[]"))
        except Exception:out=""
        if out:QApplication.clipboard().setText(out);_novav71_report(browser,"Başlık taslağı",out)
        else:QMessageBox.information(browser,"Başlık taslağı","Başlık bulunamadı.")
    _novav71_js(browser,script,done)


def _novav71_form_audit(browser):
    script="JSON.stringify(Array.from(document.forms).map((f,i)=>({form:i+1,action:f.action||location.href,method:(f.method||'get').toUpperCase(),fields:Array.from(f.querySelectorAll('input,select,textarea,button')).map(x=>({tag:x.tagName,type:x.type||'',name:x.name||'',label:x.getAttribute('aria-label')||x.labels?.[0]?.innerText||''}))})))"
    def done(raw):
        try:data=json.loads(raw or "[]");text=json.dumps(data,ensure_ascii=False,indent=2)
        except Exception:text=str(raw)
        _novav71_report(browser,"Form güvenlik özeti",text if text!="[]" else "Form bulunamadı. Alan değerleri özellikle okunmaz veya rapora eklenmez.")
    _novav71_js(browser,script,done)


def _novav71_a11y(browser):
    script="JSON.stringify({images:document.images.length,imagesMissingAlt:Array.from(document.images).filter(i=>!i.hasAttribute('alt')).length,buttons:document.querySelectorAll('button,[role=button]').length,buttonsNoName:Array.from(document.querySelectorAll('button,[role=button]')).filter(b=>!(b.innerText||'').trim()&&!b.getAttribute('aria-label')&&!b.title).length,links:document.links.length,linksNoText:Array.from(document.links).filter(a=>!(a.innerText||'').trim()&&!a.getAttribute('aria-label')).length,inputs:document.querySelectorAll('input,textarea,select').length,inputsNoLabel:Array.from(document.querySelectorAll('input,textarea,select')).filter(x=>!x.labels?.length&&!x.getAttribute('aria-label')&&!x.title).length})"
    _novav71_js(browser,script,lambda raw:_novav71_report(browser,"Erişilebilirlik hızlı denetimi",json.dumps(json.loads(raw or "{}"),ensure_ascii=False,indent=2)))


def _novav71_viewport(browser):
    script="JSON.stringify({window:{width:innerWidth,height:innerHeight},document:{width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight},screen:{width:screen.width,height:screen.height},devicePixelRatio:devicePixelRatio,colorScheme:matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light',language:navigator.language,platform:navigator.platform})"
    _novav71_js(browser,script,lambda raw:_novav71_report(browser,"Görüntü alanı raporu",json.dumps(json.loads(raw or "{}"),ensure_ascii=False,indent=2)))


def _novav71_system_browser(browser):
    url=_oss22_url_for_browser(browser)
    if not is_web_url(url):QMessageBox.information(browser,"Varsayılan tarayıcı","Geçerli HTTP/HTTPS URL bulunamadı.");return
    if not QDesktopServices.openUrl(QUrl(url)):QMessageBox.warning(browser,"Varsayılan tarayıcı","URL varsayılan tarayıcıda açılamadı.")


_NOVAOSV71_HANDLERS = {
    "pytub_launch": _novav71_launch_pytub,
    "qr_create": _novav71_qr,
    "clipboard_tools": _novav71_clipboard,
    "scratchpad": _novav71_scratchpad,
    "open_download_dir": lambda b: _novav71_open_folder(b, DOWNLOAD_DIR),
    "open_app_dir": lambda b: _novav71_open_folder(b, APP_DIR),
    "export_session": _novav71_export_session,
    "restore_session": _novav71_restore_session,
    "bookmark_find": _novav71_find_bookmark,
    "clear_domain_history": _novav71_clear_domain_history,
    "link_domains": _novav71_link_domains,
    "page_text_save": _novav71_page_text_save,
    "tables_export_csv": _novav71_tables_csv,
    "regex_lab": _novav71_regex,
    "text_diff": _novav71_text_diff,
    "base64_codec": _novav71_base64,
    "url_codec": _novav71_url_codec,
    "hash_tool": _novav71_hash,
    "json_format": _novav71_json_format,
    "csv_preview": _novav71_csv_preview,
    "timestamp_convert": _novav71_timestamp,
    "unit_convert": _novav71_units,
    "color_convert": _novav71_color,
    "text_sort_unique": _novav71_sort_unique,
    "text_case": _novav71_case,
    "word_frequency": _novav71_word_frequency,
    "markdown_preview": _novav71_markdown,
    "html_preview": _novav71_html_preview,
    "selection_search": _novav71_selection_search,
    "copy_canonical": _novav71_canonical,
    "screenshot_view": _novav71_screenshot,
    "page_pdf": _novav71_page_pdf,
    "clear_cache": _novav71_clear_cache,
    "clear_cookies": _novav71_clear_cookies,
    "search_engine_picker": _novav71_engine,
    "reader_toggle": _novav71_reader,
    "image_toggle": _novav71_images_toggle,
    "speech_read": _novav71_speech,
    "speech_stop": _novav71_speech_stop,
    "duplicate_tab": _novav71_duplicate,
    "close_other_tabs": _novav71_close_others,
    "mute_tab": _novav71_mute,
    "save_tab_session": _novav71_save_tab_session,
    "reopen_tab": _novav71_reopen_tab,
    "copy_images_list": _novav71_copy_images,
    "copy_headings": _novav71_copy_headings,
    "form_audit": _novav71_form_audit,
    "a11y_audit": _novav71_a11y,
    "viewport_report": _novav71_viewport,
    "open_system_browser": _novav71_system_browser,
}

_NOVAOSV71_PREV_DISPATCH = _oss22_dispatch
def _novav71_dispatch(browser, key):
    fn=_NOVAOSV71_HANDLERS.get(key)
    if fn:
        try: fn(browser)
        except Exception as exc: QMessageBox.warning(browser, "NOVAOS V7.1 aracı", f"İşlem tamamlanamadı:\n{exc}")
    else:
        _NOVAOSV71_PREV_DISPATCH(browser,key)
_oss22_dispatch = _novav71_dispatch

# The feature center is searchable; add 50 entries (PyTube + 49 utility tools).
_NOVAOSV71_PREV_FEATURE_INIT = OSS22FeatureCenter.__init__
def _novav71_feature_init(self, browser):
    _NOVAOSV71_PREV_FEATURE_INIT(self,browser)
    self.setWindowTitle("NOVAOS V7.1 — 140 Araç")
    for label in self.findChildren(QLabel):
        if "NOVAOS V7 / 90 ARAÇ" in label.text():
            label.setText("NOVAOS V7.1 / 140 ARAÇ · 50 YENİ ARAÇ + PyTube")
        elif "90 araç:" in label.text() or "52 işlevsel araç" in label.text():
            label.setText("140 araç: önceki araçlar + 50 yeni işlev ve PyTube Video İndirici entegrasyonu.")
OSS22FeatureCenter.__init__ = _novav71_feature_init

# Add a visible PyTube link to the one-page NOVA home, without bringing back
# the old Discover cards. This route is intercepted locally by BrowserPage.
_NOVAOSV71_PREV_HOME_HTML = _nova_home_html
def _novav71_home_html(engine_name="NOVA Search", shortcuts=None, browser=None):
    output = _NOVAOSV71_PREV_HOME_HTML(engine_name,shortcuts,browser)
    action = '<a class="action" href="https://ossbrowser.local/pytub"><span class="ico">▶</span>PyTube Video İndirici</a>'
    marker = '</section><div class="quick-head">'
    if marker in output and 'href="https://ossbrowser.local/pytub"' not in output:
        output = output.replace(marker, action + marker, 1)
    return output
_nova_home_html = _novav71_home_html

_NOVAOSV71_PREV_NAV = BrowserPage.acceptNavigationRequest
def _novav71_navigation(self, url, nav_type, is_main_frame):
    try:
        if is_main_frame and (url.host() or "").lower() == NOVA_SEARCH_HOST and (url.path() or "/").rstrip("/") == "/pytub":
            QTimer.singleShot(0, lambda b=self.browser: _novav71_launch_pytub(b))
            return False
    except Exception:
        pass
    return _NOVAOSV71_PREV_NAV(self,url,nav_type,is_main_frame)
BrowserPage.acceptNavigationRequest = _novav71_navigation

_NOVAOSV71_PREV_SETUP_UI = MainWindow.setup_ui
def _novav71_setup_ui(self,*args,**kwargs):
    _NOVAOSV71_PREV_SETUP_UI(self,*args,**kwargs)
    try:
        button=getattr(self,"tools_button",None); menu=button.menu() if button else None
        if menu is not None and not getattr(self,"_novav71_pytub_menu_added",False):
            self._novav71_pytub_menu_added=True
            menu.addSeparator()
            menu.addAction("PyTube Video İndirici",lambda b=self:_novav71_launch_pytub(b))
            menu.addAction("NOVAOS V7.1 — 140 Araç",lambda b=self:OSS22FeatureCenter(b).exec())
    except Exception as exc:
        try:self.statusBar().showMessage("PyTube/NOVAOS menüsü: "+str(exc),3500)
        except Exception:pass
MainWindow.setup_ui = _novav71_setup_ui

_NOVAOSV71_PREV_INIT = MainWindow.__init__
def _novav71_init(self,*args,**kwargs):
    _NOVAOSV71_PREV_INIT(self,*args,**kwargs)
    QTimer.singleShot(900,lambda b=self:_novav71_setup_late_menu(b))
    try:
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.data.setdefault("settings",{}).setdefault("pytub_exe_path","")
    except Exception:pass

def _novav71_setup_late_menu(browser):
    try:
        button=getattr(browser,"tools_button",None);menu=button.menu() if button else None
        if menu is None or getattr(browser,"_novav71_pytub_menu_added",False):return
        browser._novav71_pytub_menu_added=True
        menu.addSeparator();menu.addAction("PyTube Video İndirici",lambda b=browser:_novav71_launch_pytub(b));menu.addAction("NOVAOS V7.1 — 140 Araç",lambda b=browser:OSS22FeatureCenter(b).exec())
    except Exception:pass
MainWindow.__init__ = _novav71_init


if __name__ == "__main__":
    main()
