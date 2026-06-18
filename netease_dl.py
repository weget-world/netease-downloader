#!/usr/bin/env python3
"""
网易云音乐搜索下载器 v2.0
- 基于 pymusiclibrary (MusicLibrary) 实现加密API调用
- 搜索歌曲 -> 选择 -> 下载 mp3 + 歌词
"""

import sys
import os
import re
import time

# ---------- 控制台 UTF-8 兼容 ----------
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_IS_WIN = sys.platform == "win32"

EMOJI_MAP = {
    "\U0001f3b5": "[M]",
    "\U0001f4c1": "[F]",
    "\u2705": "[OK]",
    "\u2716": "[X]",
    "\u26a0": "[!]",
    "\U0001f50d": "[S]",
    "\U0001f4cb": "[L]",
    "\U0001f3af": "[T]",
    "\U0001f44b": "[BYE]",
    "\U0001f615": "[NO]",
}


def _t(text):
    for e, r in EMOJI_MAP.items():
        text = text.replace(e, r)
    return text


# ---------------------------------------

from MusicLibrary.neteaseCloudMusicApi import NeteaseCloudMusicApi

VERSION = "2.0.0"

# 获取 exe/脚本所在目录（打包后不指向临时路径）
if getattr(sys, 'frozen', False):
    # 打包成 exe 时
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 普通 .py 运行时
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")

api = NeteaseCloudMusicApi()


def safe_filename(name: str) -> str:
    # 去掉 Windows 文件名非法字符，/ 也替换掉
    sanitized = re.sub(r'[<>:"\\|?*/]', "", name).strip()
    return sanitized or "unknown"


def fmt_time(ms: int) -> str:
    if not ms:
        return "?:??"
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def search_and_show(keyword: str, limit: int = 20) -> list:
    """搜索并打印结果，返回歌曲列表"""
    print(_t(f"\n[S] 正在搜索 \"{keyword}\"..."))
    resp = api.search(keyword)
    body = getattr(resp, "body", resp)
    if not body:
        print(_t("[X] 搜索无响应"))
        return []

    if isinstance(body, dict):
        code = body.get("code", -1)
        if code != 200:
            print(_t(f"[X] API返回异常: code={code}"))
            return []

        songs = (
            body.get("result", {})
            .get("songs", [])
            if isinstance(body.get("result"), dict)
            else []
        )
    else:
        # 可能直接是列表
        songs = body if isinstance(body, list) else []

    if not songs:
        print(_t("[NO] 没有找到相关歌曲\n"))
        return []

    print(_t(f"\n[L] 搜索结果 (共 {len(songs)} 首):"))
    print("-" * 80)
    for i, song in enumerate(songs, 1):
        sid = song.get("id", "?")
        name = song.get("name", "未知")
        artists = " / ".join(a.get("name", "?") for a in song.get("artists", []))
        album = song.get("album", {}).get("name", "未知专辑")
        duration = fmt_time(song.get("duration", 0))
        print(f"  [{i:>2}] {name} -- {artists}")
        print(f"        专辑: {album}  [{duration}]  ID:{sid}")
    print("-" * 80)
    return songs


def get_song_url(song_id: int) -> str:
    """通过 song_url API 获取真实播放链接"""
    resp = api.song_url(song_id)
    body = getattr(resp, "body", resp)
    if not body or not isinstance(body, dict):
        return ""
    if body.get("code") != 200:
        return ""
    data = body.get("data", [])
    if not data:
        return ""
    url = data[0].get("url", "")
    return url if url else ""


def get_song_url_v1(song_id: int, level: str = "standard") -> str:
    """song_url_v1 支持音质选择: standard / higher / exhigh / lossless / hires"""
    resp = api.song_url_v1(song_id, level)
    body = getattr(resp, "body", resp)
    if not body or not isinstance(body, dict):
        return ""
    if body.get("code") != 200:
        return ""
    data = body.get("data", [])
    if not data:
        return ""
    url = data[0].get("url", "")
    return url if url else ""


def download_mp3(url: str, filepath: str, label: str) -> bool:
    """从URL下载mp3到文件"""
    import requests

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://music.163.com/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30, stream=True)
        if resp.status_code != 200:
            print(_t(f"    [X] HTTP {resp.status_code}: {label}"))
            return False

        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded * 100 // total
                        print(f"\r    [下载] {pct}%", end="", flush=True)
        size_kb = downloaded / 1024
        print(f"\r    [OK] {filepath} ({size_kb:.0f} KB)")
        return True

    except Exception as e:
        print(_t(f"    [X] 下载异常: {e}"))
        return False


def download_lyrics(song_id: int, filepath: str):
    """下载歌词(.lrc)"""
    try:
        resp = api.lyric(song_id)
        body = getattr(resp, "body", resp)
        if not body or not isinstance(body, dict):
            return
        lrc = body.get("lrc", {}).get("lyric", "")
        if lrc:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(lrc)
            print(f"    [OK] 歌词已保存")
    except Exception:
        pass


def download_song(song: dict, outdir: str, with_lyrics: bool = True) -> bool:
    """下载单首歌"""
    song_id = song.get("id")
    if not song_id:
        print(_t("    [X] 无效歌曲ID"))
        return False

    name = song.get("name", "未知")
    artists = " / ".join(a.get("name", "?") for a in song.get("artists", []))
    base = f"{safe_filename(artists)} - {safe_filename(name)}"
    mp3_path = os.path.join(outdir, f"{base}.mp3")
    lrc_path = os.path.join(outdir, f"{base}.lrc")

    # 检查是否已存在
    if os.path.exists(mp3_path):
        print(_t(f"    [OK] 已存在，跳过: {base}.mp3"))
        return True

    # 获取播放URL
    print(_t(f"    [S] 获取链接..."), end="")
    url = get_song_url_v1(song_id, "standard")
    if not url:
        url = get_song_url(song_id)
    if not url:
        # 尝试非加密外链（部分歌曲可用）
        url = f"https://music.163.com/song/media/outer/url?id={song_id}.mp3"
        print(_t(" 外链备用"), end="")
    else:
        print(_t(" OK"), end="")
    print()

    # 下载mp3
    success = download_mp3(url, mp3_path, base)

    # 下载歌词
    if success and with_lyrics:
        if not os.path.exists(lrc_path):
            download_lyrics(song_id, lrc_path)

    time.sleep(0.3)  # 礼貌间隔
    return success


def main():
    print(_t(f"[M] 网易云音乐搜索下载器 v{VERSION}"))
    print(_t(f"[F] 下载目录: {DOWNLOAD_DIR}"))
    print()

    while True:
        keyword = input("> 输入歌名或歌手 (直接回车退出): ").strip()
        if not keyword:
            print(_t("[BYE] 再见！"))
            break

        songs = search_and_show(keyword)
        if not songs:
            continue

        choice = (
            input(_t("\n[T] 输入编号下载 (空格分隔多选，a=全部，回车跳过): "))
            .strip()
            .lower()
        )
        if not choice:
            print()
            continue

        selected = []
        if choice == "a":
            selected = list(range(len(songs)))
        else:
            for part in choice.split():
                try:
                    idx = int(part)
                    if 1 <= idx <= len(songs):
                        selected.append(idx - 1)
                    else:
                        print(_t(f"  [!] 跳过无效编号: {part}"))
                except ValueError:
                    print(_t(f"  [!] 跳过无效输入: {part}"))

        if not selected:
            print(_t("  未选择任何有效编号\n"))
            continue

        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        print(_t(f"\n[下载] 开始下载 {len(selected)} 首到: {DOWNLOAD_DIR}"))
        print("-" * 80)
        success = 0
        for idx in selected:
            song = songs[idx]
            print(f"\n  [{idx + 1}/{len(songs)}] {song.get('name', '?')}")
            if download_song(song, DOWNLOAD_DIR, with_lyrics=True):
                success += 1

        print("-" * 80)
        print(_t(f"[OK] 完成: {success}/{len(selected)} 首下载成功\n"))


if __name__ == "__main__":
    main()
