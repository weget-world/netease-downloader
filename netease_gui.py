#!/usr/bin/env python3
"""
网易云音乐搜索下载器 v2.1 - GUI版（带翻页）
- 基于 pymusiclibrary (MusicLibrary) 实现加密API调用
- 搜索歌曲 -> 选择 -> 下载 mp3 + 歌词
- 纯 tkinter 图形界面，零额外依赖
"""

import sys
import os
import re
import time
import datetime
import traceback
import threading

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------- 第三方库导入 ----------
from MusicLibrary.neteaseCloudMusicApi import NeteaseCloudMusicApi
import requests

# ---------- tkinter ----------
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
except ImportError:
    print("错误: 需要 tkinter。请使用完整 Python 安装。")
    sys.exit(1)

# ---------------------------------------------------------------------------
#  路径
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

VERSION = "2.1.0"
PAGE_SIZE = 30  # 每页歌曲数

# ---------------------------------------------------------------------------
#  API 封装
# ---------------------------------------------------------------------------
class NeteaseAPI:
    def __init__(self):
        self._api = NeteaseCloudMusicApi()
        self._lock = threading.Lock()

    def search(self, keyword: str, limit: int = PAGE_SIZE, offset: int = 0):
        """返回 (songs_list, total_count)"""
        with self._lock:
            try:
                resp = self._api.search(keyword, limit=limit, offset=offset)
                body = getattr(resp, "body", resp)
                if not body:
                    log.warn("api", f"search({keyword}) 返回空")
                    return [], 0
                if isinstance(body, dict) and body.get("code") == 200:
                    result = body.get("result", {})
                    if isinstance(result, dict):
                        songs = result.get("songs", [])
                        total = result.get("songCount", 0) or len(songs)
                        log.info("api", f"search({keyword}) offset={offset} => {len(songs)}/{total}")
                        return songs, total
                    return [], 0
                if isinstance(body, list):
                    return body, len(body)
                log.warn("api", f"search({keyword}) 异常响应: {type(body).__name__}")
                return [], 0
            except Exception as e:
                log.exception("api", e)
                return [], 0

    def get_url(self, song_id: int) -> str:
        with self._lock:
            try:
                resp = self._api.song_url_v1(song_id, "standard")
                body = getattr(resp, "body", resp)
                if body and isinstance(body, dict) and body.get("code") == 200:
                    data = body.get("data", [])
                    if data and data[0].get("url"):
                        return data[0]["url"]
                resp2 = self._api.song_url(song_id)
                body2 = getattr(resp2, "body", resp2)
                if body2 and isinstance(body2, dict) and body2.get("code") == 200:
                    data2 = body2.get("data", [])
                    if data2 and data2[0].get("url"):
                        return data2[0]["url"]
                log.warn("api", f"get_url({song_id}) fallback 到公开外链")
                return f"https://music.163.com/song/media/outer/url?id={song_id}.mp3"
            except Exception as e:
                log.exception("api", e)
                return ""

    def get_lyric(self, song_id: int) -> str:
        with self._lock:
            try:
                resp = self._api.lyric(song_id)
                body = getattr(resp, "body", resp)
                if body and isinstance(body, dict):
                    lyric = body.get("lrc", {}).get("lyric", "")
                    return lyric
            except Exception as e:
                log.warn("api", f"get_lyric({song_id}) 失败: {e}")
            return ""


_api_inst = None
_api_lock = threading.Lock()
def get_api():
    global _api_inst
    with _api_lock:
        if _api_inst is None:
            _api_inst = NeteaseAPI()
        return _api_inst


# ---------------------------------------------------------------------------
#  文件日志
# ---------------------------------------------------------------------------
class FileLogger:
    """全局文件日志：每条记录带时间戳，自动按天分文件，线程安全"""
    def __init__(self):
        self._today = ""
        self._fh = None
        self._lock = threading.Lock()
        self._rotate()

    def _rotate(self):
        """检查日期，跨天则换文件"""
        today = datetime.date.today().isoformat()
        if today == self._today and self._fh:
            return
        self.close()
        path = os.path.join(LOG_DIR, f"{today}.log")
        try:
            self._fh = open(path, "a", encoding="utf-8")
            self._today = today
        except Exception:
            self._fh = None

    def write(self, level: str, source: str, msg: str):
        """写一行日志：`[2026-06-17 08:30:00] [INFO] [search] 消息`"""
        with self._lock:
            try:
                self._rotate()
                if self._fh is None:
                    return
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._fh.write(f"[{ts}] [{level}] [{source}] {msg}\n")
                self._fh.flush()
            except Exception:
                pass

    def info(self, source: str, msg: str):
        self.write("INFO", source, msg)

    def warn(self, source: str, msg: str):
        self.write("WARN", source, msg)

    def error(self, source: str, msg: str):
        self.write("ERROR", source, msg)

    def exception(self, source: str, exc: Exception):
        """记录异常+调用栈"""
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        with self._lock:
            self.write("ERROR", source, f"{type(exc).__name__}: {exc}")
            for line in tb:
                self.write("ERROR", source, line.rstrip())

    def close(self):
        if self._fh:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None

    def __del__(self):
        self.close()


# 全局日志实例
log = FileLogger()


# ---------------------------------------------------------------------------
#  工具函数
# ---------------------------------------------------------------------------
def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"\\|?*/]', "", name).strip() or "unknown"

def fmt_time(ms: int) -> str:
    if not ms:
        return "?:??"
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"

def fmt_size(bytes_: int) -> str:
    if bytes_ < 1024:
        return f"{bytes_} B"
    elif bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.0f} KB"
    else:
        return f"{bytes_ / 1024 / 1024:.1f} MB"


# ---------------------------------------------------------------------------
#  配色
# ---------------------------------------------------------------------------
COLORS = {
    "bg": "#F5F5F5",
    "fg": "#333333",
    "accent": "#C20C0C",
    "accent_hover": "#A30A0A",
    "white": "#FFFFFF",
    "border": "#E0E0E0",
    "selected_bg": "#FFE0E0",
    "log_bg": "#1E1E1E",
    "log_fg": "#D4D4D4",
    "info": "#1565C0",
}


# ---------------------------------------------------------------------------
#  主窗口
# ---------------------------------------------------------------------------
class NeteaseMusicApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("网易云音乐下载器")
        self.root.geometry("860x720")
        self.root.minsize(740, 580)
        self.root.configure(bg=COLORS["bg"])

        try:
            self.root.iconbitmap(default=os.path.join(BASE_DIR, "icon.ico"))
        except Exception:
            pass

        # 状态
        self.all_results = []       # 所有页累计的歌曲列表
        self.current_page = 0
        self.total_songs = 0
        self.search_keyword = ""
        self.searching = False
        self.downloading = False
        self.selected_indices = set()
        self.download_dir = tk.StringVar(value=DOWNLOAD_DIR)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ==================================================================
    #  UI 构建
    # ==================================================================
    def _build_ui(self):
        root = self.root

        # ---- 标题栏 ----
        header = tk.Frame(root, bg=COLORS["accent"], height=48)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="网易云音乐下载器", fg="white",
                 bg=COLORS["accent"], font=("Microsoft YaHei UI", 16, "bold")
                 ).pack(side="left", padx=16, pady=6)
        tk.Label(header, text=f"v{VERSION}", fg="#FFAAAA",
                 bg=COLORS["accent"], font=("Microsoft YaHei UI", 10)
                 ).pack(side="left", padx=(0, 10))

        # ---- 搜索区域 ----
        sf = tk.Frame(root, bg=COLORS["bg"], padx=16, pady=12)
        sf.pack(fill="x")

        srow = tk.Frame(sf, bg=COLORS["bg"])
        srow.pack(fill="x")
        tk.Label(srow, text="搜索歌曲 / 歌手：", bg=COLORS["bg"],
                 fg=COLORS["fg"], font=("Microsoft YaHei UI", 11)).pack(side="left")

        self.search_entry = tk.Entry(srow, textvariable=tk.StringVar(),
                                     font=("Microsoft YaHei UI", 12),
                                     relief="solid", bd=1,
                                     highlightthickness=1,
                                     highlightcolor=COLORS["accent"],
                                     highlightbackground=COLORS["border"])
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.search_entry.bind("<Return>", lambda e: self._do_search())

        self.search_btn = tk.Button(srow, text="🔍 搜索",
                                    font=("Microsoft YaHei UI", 10, "bold"),
                                    bg=COLORS["accent"], fg="white",
                                    relief="flat", padx=16, pady=4,
                                    cursor="hand2",
                                    activebackground=COLORS["accent_hover"],
                                    activeforeground="white",
                                    command=self._do_search)
        self.search_btn.pack(side="left")

        # ---- 翻页指示栏 ----
        self.page_frame = tk.Frame(root, bg=COLORS["bg"], padx=16)
        self.page_frame.pack(fill="x", pady=(0, 4))
        self.page_label = tk.Label(self.page_frame, text="",
                                   bg=COLORS["bg"], fg=COLORS["accent"],
                                   font=("Microsoft YaHei UI", 10))
        self.page_label.pack(side="left", padx=(0, 12))

        self.prev_btn = tk.Button(self.page_frame, text="◀ 上一页",
                                  font=("Microsoft YaHei UI", 9),
                                  bg=COLORS["white"], fg=COLORS["fg"],
                                  relief="solid", bd=1, padx=10,
                                  cursor="hand2", state="disabled",
                                  command=self._prev_page)
        self.prev_btn.pack(side="left", padx=(0, 4))

        self.next_btn = tk.Button(self.page_frame, text="下一页 ▶",
                                  font=("Microsoft YaHei UI", 9),
                                  bg=COLORS["white"], fg=COLORS["fg"],
                                  relief="solid", bd=1, padx=10,
                                  cursor="hand2", state="disabled",
                                  command=self._next_page)
        self.next_btn.pack(side="left")

        self.load_all_btn = tk.Button(self.page_frame, text="加载全部",
                                      font=("Microsoft YaHei UI", 9),
                                      bg=COLORS["accent"], fg="white",
                                      relief="flat", padx=12,
                                      cursor="hand2", state="disabled",
                                      activebackground=COLORS["accent_hover"],
                                      command=self._load_all)
        self.load_all_btn.pack(side="left", padx=(8, 0))

        # ---- 结果表格 ----
        rf = tk.Frame(root, bg=COLORS["bg"], padx=16)
        rf.pack(fill="both", expand=True, pady=(0, 8))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Result.Treeview", font=("Microsoft YaHei UI", 10),
                        rowheight=32, background=COLORS["white"],
                        fieldbackground=COLORS["white"],
                        foreground=COLORS["fg"], borderwidth=0)
        style.configure("Result.Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"),
                        background=COLORS["accent"], foreground="white", borderwidth=0)
        style.map("Result.Treeview",
                  background=[("selected", COLORS["selected_bg"])],
                  foreground=[("selected", COLORS["accent"])])

        columns = ("sel", "idx", "name", "artist", "album", "duration")
        self.tree = ttk.Treeview(rf, columns=columns, show="headings",
                                 selectmode="extended", style="Result.Treeview", height=14)
        self.tree.heading("sel", text="☐", anchor="center")
        self.tree.heading("idx", text="#", anchor="center")
        self.tree.heading("name", text="歌曲名", anchor="w")
        self.tree.heading("artist", text="歌手", anchor="w")
        self.tree.heading("album", text="专辑", anchor="w")
        self.tree.heading("duration", text="时长", anchor="center")

        self.tree.column("sel", width=36, minwidth=36, anchor="center")
        self.tree.column("idx", width=44, minwidth=36, anchor="center")
        self.tree.column("name", width=240, minwidth=140)
        self.tree.column("artist", width=180, minwidth=100)
        self.tree.column("album", width=200, minwidth=100)
        self.tree.column("duration", width=70, minwidth=60, anchor="center")

        vsb = ttk.Scrollbar(rf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)

        # ---- 底部操作栏 ----
        bf = tk.Frame(root, bg=COLORS["bg"], padx=16)
        bf.pack(fill="x", pady=8)

        row1 = tk.Frame(bf, bg=COLORS["bg"])
        row1.pack(fill="x", pady=6)

        tk.Label(row1, text="下载到：", bg=COLORS["bg"],
                 fg=COLORS["fg"], font=("Microsoft YaHei UI", 10)).pack(side="left")

        self.dir_label = tk.Label(row1, textvariable=self.download_dir,
                                  bg=COLORS["white"], fg=COLORS["info"],
                                  font=("Microsoft YaHei UI", 9),
                                  relief="solid", bd=1, padx=8, pady=2)
        self.dir_label.pack(side="left", fill="x", expand=True, padx=(4, 8))

        self.browse_btn = tk.Button(row1, text="📁 浏览",
                                    font=("Microsoft YaHei UI", 9),
                                    bg=COLORS["white"], fg=COLORS["fg"],
                                    relief="solid", bd=1, padx=10,
                                    cursor="hand2", command=self._browse_dir)
        self.browse_btn.pack(side="left", padx=(0, 6))

        self.select_all_btn = tk.Button(row1, text="☑ 全选",
                                        font=("Microsoft YaHei UI", 9),
                                        bg=COLORS["white"], fg=COLORS["fg"],
                                        relief="solid", bd=1, padx=10,
                                        cursor="hand2",
                                        command=self._toggle_select_all)
        self.select_all_btn.pack(side="left", padx=2)

        self.download_btn = tk.Button(row1, text="⬇ 下载选中",
                                      font=("Microsoft YaHei UI", 10, "bold"),
                                      bg=COLORS["accent"], fg="white",
                                      relief="flat", padx=18, pady=4,
                                      cursor="hand2",
                                      activebackground=COLORS["accent_hover"],
                                      activeforeground="white",
                                      command=self._do_download)
        self.download_btn.pack(side="left", padx=(8, 0))

        self.open_dir_btn = tk.Button(row1, text="📂 打开下载目录",
                                      font=("Microsoft YaHei UI", 9),
                                      bg=COLORS["white"], fg=COLORS["fg"],
                                      relief="solid", bd=1, padx=10,
                                      cursor="hand2", command=self._open_dir)
        self.open_dir_btn.pack(side="right")

        # ---- 日志 ----
        lf = tk.Frame(root, bg=COLORS["log_bg"])
        lf.pack(fill="x", padx=16, pady=(0, 12))

        self.log_text = tk.Text(lf, height=7, bg=COLORS["log_bg"],
                                fg=COLORS["log_fg"], font=("Consolas", 9),
                                relief="flat", bd=0, wrap="word",
                                state="disabled")
        self.log_text.pack(fill="both", side="left", expand=True)

        lsc = ttk.Scrollbar(lf, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=lsc.set)
        lsc.pack(side="right", fill="y")

        # ---- 进度条 ----
        self.progress = ttk.Progressbar(root, mode="determinate", length=0,
                                        style="red.Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=16, pady=(0, 12))

        style.configure("red.Horizontal.TProgressbar",
                        background=COLORS["accent"], troughcolor=COLORS["border"])

        self._log(f"网易云音乐下载器 v{VERSION} 已启动", "INFO", "startup")
        self._log(f"下载目录: {DOWNLOAD_DIR}", "INFO", "startup")

    # ==================================================================
    #  搜索 + 翻页
    # ==================================================================
    def _do_search(self):
        kw = self.search_entry.get().strip()
        if not kw:
            messagebox.showwarning("提示", "请输入歌名或歌手名")
            return

        self.search_keyword = kw
        self.current_page = 0
        self.all_results = []
        self.selected_indices = set()

        # 清空表格
        for item in self.tree.get_children():
            self.tree.delete(item)

        self._update_page_ui()
        self.search_btn.configure(state="disabled", text="搜索中…")
        self._log(f"正在搜索 \"{kw}\"...", "INFO", "search")

        t = threading.Thread(target=self._fetch_page, args=(0, False), daemon=True)
        t.start()

    def _fetch_page(self, page: int, append: bool):
        """请求第 page 页（0-indexed）"""
        api = get_api()
        offset = page * PAGE_SIZE
        songs, total = api.search(self.search_keyword, limit=PAGE_SIZE, offset=offset)

        self.root.after(0, self._on_page_fetched, page, songs, total, append)

    def _on_page_fetched(self, page, songs, total, append):
        if not append:
            # 首次搜索，清空
            self.all_results = []
            for item in self.tree.get_children():
                self.tree.delete(item)

        self.total_songs = total

        # 补空白（如果跳过了中间页）
        while len(self.all_results) < page * PAGE_SIZE:
            self.all_results.append(None)

        # 填入当前页
        for i, song in enumerate(songs):
            idx = page * PAGE_SIZE + i
            if idx < len(self.all_results):
                self.all_results[idx] = song
            else:
                self.all_results.append(song)

        # 刷新界面表格
        self._refresh_table()

        self.search_btn.configure(state="normal", text="🔍 搜索")
        self._update_page_ui()

        loaded = len([s for s in self.all_results if s is not None])
        self._log(f"已加载 {loaded}/{total} 首 (第 {page+1} 页)", "INFO", "search")

    def _refresh_table(self):
        """用 all_results 刷新当前表格显示"""
        # 清表格
        for item in self.tree.get_children():
            self.tree.delete(item)

        start = self.current_page * PAGE_SIZE
        end = min(start + PAGE_SIZE, len(self.all_results))
        visible = self.all_results[start:end]

        for i, song in enumerate(visible):
            if song is None:
                continue
            global_idx = start + i
            sid = song.get("id", "?")
            name = song.get("name", "未知")
            artists = " / ".join(a.get("name", "?") for a in song.get("artists", []))
            album = song.get("album", {}).get("name", "未知专辑")
            duration = fmt_time(song.get("duration", 0))

            checked = "☑" if global_idx in self.selected_indices else ""
            vals = (checked, str(global_idx + 1), name, artists, album, duration)
            self.tree.insert("", "end", values=vals, iid=str(global_idx))

        self._update_select_all_btn()

    def _update_page_ui(self):
        loaded = len([s for s in self.all_results if s is not None])
        total = self.total_songs
        page = self.current_page

        if loaded == 0:
            self.page_label.configure(text="")
            self.prev_btn.configure(state="disabled")
            self.next_btn.configure(state="disabled")
            self.load_all_btn.configure(state="disabled")
            return

        text = f"第 {page+1} 页 / 共 {loaded} 首 (总计 {total} 首)"
        self.page_label.configure(text=text)

        # 上一页
        self.prev_btn.configure(state="normal" if page > 0 else "disabled")

        # 下一页：还有更多可以加载
        can_next = (page + 1) * PAGE_SIZE < total
        self.next_btn.configure(state="normal" if can_next else "disabled")

        # 加载全部
        remaining = total - loaded
        self.load_all_btn.configure(
            state="normal" if remaining > 0 else "disabled",
            text=f"加载全部 ({remaining})" if remaining > 0 else "全部已加载"
        )

    def _prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._refresh_table()
            self._update_page_ui()

    def _next_page(self):
        next_page = self.current_page + 1
        # 如果还没加载过这页，去加载
        loaded_count = len([s for s in self.all_results if s is not None])
        need_load = (next_page + 1) * PAGE_SIZE > loaded_count

        if need_load and (next_page * PAGE_SIZE) < self.total_songs:
            # 加载下一页
            self.current_page = next_page
            self.search_btn.configure(state="disabled", text="加载中…")
            t = threading.Thread(target=self._fetch_page, args=(next_page, True), daemon=True)
            t.start()
        else:
            self.current_page = next_page
            self._refresh_table()
            self._update_page_ui()

    def _load_all(self):
        """加载全部剩余页"""
        t = threading.Thread(target=self._load_all_thread, daemon=True)
        t.start()

    def _load_all_thread(self):
        loaded = len([s for s in self.all_results if s is not None])
        total = self.total_songs

        while loaded < total:
            page = loaded // PAGE_SIZE
            api = get_api()
            songs, _ = api.search(self.search_keyword, limit=PAGE_SIZE, offset=page * PAGE_SIZE)

            # 补空白
            while len(self.all_results) < page * PAGE_SIZE:
                self.all_results.append(None)

            for i, song in enumerate(songs):
                idx = page * PAGE_SIZE + i
                if idx < len(self.all_results):
                    self.all_results[idx] = song
                else:
                    self.all_results.append(song)

            loaded = len([s for s in self.all_results if s is not None])
            self.root.after(0, self._update_load_all_progress, loaded, total)

            if len(songs) < PAGE_SIZE:
                break
            time.sleep(0.5)

        self.root.after(0, self._on_load_all_done)

    def _update_load_all_progress(self, loaded, total):
        self._log(f"加载中… {loaded}/{total}", "INFO", "search")
        self.load_all_btn.configure(text=f"加载中… ({loaded}/{total})")

    def _on_load_all_done(self):
        self._refresh_table()
        self._update_page_ui()
        self.search_btn.configure(state="normal", text="🔍 搜索")
        self._log(f"已全部加载完 {self.total_songs} 首", "INFO", "search")

    # ==================================================================
    #  选择
    # ==================================================================
    def _on_tree_click(self, event):
        col = self.tree.identify_column(event.x)
        item = self.tree.identify_row(event.y)
        if not item:
            return
        idx = int(item)

        if col == "#0" or col == "#1":
            self._toggle_item(idx)
        else:
            if idx in self.selected_indices:
                self.selected_indices.discard(idx)
            else:
                self.selected_indices.add(idx)
            self._update_tree_selection()

    def _toggle_item(self, idx):
        if idx in self.selected_indices:
            self.selected_indices.discard(idx)
        else:
            self.selected_indices.add(idx)
        self._update_tree_selection()

    def _toggle_select_all(self):
        total = len([s for s in self.all_results if s is not None])
        if len(self.selected_indices) == total:
            self.selected_indices.clear()
        else:
            self.selected_indices = {
                i for i, s in enumerate(self.all_results) if s is not None
            }
        self._update_tree_selection()

    def _update_select_all_btn(self):
        total = len([s for s in self.all_results if s is not None])
        sel = len(self.selected_indices)
        if total == 0:
            self.select_all_btn.configure(text="☑ 全选")
        elif sel == total:
            self.select_all_btn.configure(text="☑ 取消全选")
        else:
            self.select_all_btn.configure(text=f"☑ 全选 ({sel})")

    def _update_tree_selection(self):
        # 刷新全部可见行
        for item in self.tree.get_children():
            idx = int(item)
            vals = list(self.tree.item(item, "values"))
            vals[0] = "☑" if idx in self.selected_indices else ""
            self.tree.item(item, values=vals)
            if idx in self.selected_indices:
                self.tree.selection_add(item)
            else:
                self.tree.selection_remove(item)
        self._update_select_all_btn()

    # ==================================================================
    #  下载
    # ==================================================================
    def _do_download(self):
        if self.downloading:
            return

        indices = sorted(self.selected_indices)
        if not indices:
            messagebox.showwarning("提示", "请先选择要下载的歌曲")
            return

        dir_path = self.download_dir.get().strip()
        if not dir_path:
            messagebox.showwarning("提示", "请选择下载目录")
            return

        os.makedirs(dir_path, exist_ok=True)

        self.downloading = True
        self.download_btn.configure(state="disabled", text="下载中…")
        self.search_btn.configure(state="disabled")
        self.select_all_btn.configure(state="disabled")
        self.browse_btn.configure(state="disabled")
        self.prev_btn.configure(state="disabled")
        self.next_btn.configure(state="disabled")
        self.load_all_btn.configure(state="disabled")
        self.progress["maximum"] = len(indices)
        self.progress["value"] = 0

        self._log(f"\n开始下载 {len(indices)} 首 -> {dir_path}", "INFO", "download")

        t = threading.Thread(target=self._download_thread,
                             args=(indices, dir_path), daemon=True)
        t.start()

    def _download_thread(self, indices, dir_path):
        api = get_api()
        success_count = 0
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://music.163.com/",
        }

        for i, idx in enumerate(indices):
            song = self.all_results[idx]
            if song is None:
                self.root.after(0, lambda i=i: self._log(f"\n[{i+1}/{len(indices)}] 跳过(未加载)", "WARN", "download"))
                self.root.after(0, self._update_progress, i + 1)
                continue

            song_id = song.get("id")
            name = song.get("name", "未知")
            artists = " / ".join(a.get("name", "?") for a in song.get("artists", []))
            base = f"{safe_filename(artists)} - {safe_filename(name)}"
            mp3_path = os.path.join(dir_path, f"{base}.mp3")
            lrc_path = os.path.join(dir_path, f"{base}.lrc")

            self.root.after(0, lambda s=song: self._log(f"\n[{i+1}/{len(indices)}] {name} - {artists}", "INFO", "download"))

            if os.path.exists(mp3_path):
                self.root.after(0, lambda: self._log(f"  已存在，跳过", "INFO", "download"))
                self.root.after(0, self._update_progress, i + 1)
                success_count += 1
                continue

            url = api.get_url(song_id)
            if not url:
                self.root.after(0, lambda: self._log(f"  ❌ 无法获取播放链接", "ERROR", "download"))
                self.root.after(0, self._update_progress, i + 1)
                continue

            try:
                resp = requests.get(url, headers=headers, timeout=30, stream=True)
                if resp.status_code != 200:
                    self.root.after(0, lambda s=resp.status_code: self._log(f"  ❌ HTTP {s}", "ERROR", "download"))
                    self.root.after(0, self._update_progress, i + 1)
                    continue

                downloaded = 0
                with open(mp3_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)

                self.root.after(0, lambda s=downloaded: self._log(f"  ✅ {fmt_size(s)}", "INFO", "download"))
                success_count += 1

                lyric = api.get_lyric(song_id)
                if lyric:
                    with open(lrc_path, "w", encoding="utf-8") as f:
                        f.write(lyric)
                    self.root.after(0, lambda: self._log(f"  📝 歌词已保存", "INFO", "download"))

            except Exception as e:
                self.root.after(0, lambda e=e: self._log(f"  ❌ 下载异常: {e}", "ERROR", "download"))

            self.root.after(0, self._update_progress, i + 1)
            time.sleep(0.3)

        self.root.after(0, self._on_download_done, success_count, len(indices))

    def _update_progress(self, value):
        self.progress["value"] = value

    def _on_download_done(self, success, total):
        self.downloading = False
        self.download_btn.configure(state="normal", text="⬇ 下载选中")
        self.search_btn.configure(state="normal")
        self.select_all_btn.configure(state="normal")
        self.browse_btn.configure(state="normal")
        self._update_page_ui()
        self.progress["value"] = 0
        self._log(f"\n✅ 下载完成: {success}/{total} 首成功\n", "INFO", "download")

    # ==================================================================
    #  目录
    # ==================================================================
    def _browse_dir(self):
        path = filedialog.askdirectory(initialdir=self.download_dir.get(), title="选择下载目录")
        if path:
            self.download_dir.set(path)
            self._log(f"下载目录已更改为: {path}", "INFO", "config")

    def _open_dir(self):
        path = self.download_dir.get()
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)
        except Exception:
            pass

    # ==================================================================
    #  日志（界面 + 文件双写）
    # ==================================================================
    def _log(self, msg, level="INFO", source="app"):
        """输出到界面文本框 + 文件日志"""
        # 界面
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        # 文件
        log.write(level, source, msg)

    # ==================================================================
    #  关闭
    # ==================================================================
    def _on_close(self):
        if self.downloading:
            if not messagebox.askokcancel("提示", "正在下载中，确定要退出吗？"):
                return
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
#  入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = NeteaseMusicApp()
    app.run()
