# 网易云音乐搜索下载器

基于 `pymusiclibrary` (MusicLibrary) 的网易云音乐搜索下载工具，带图形界面和翻页功能。

## 功能

- 🔍 **搜索歌曲** — 输入歌名或歌手名，搜索网易云音乐曲库
- 📄 **翻页浏览** — 每页 30 首，支持上一页/下一页/加载全部
- ✅ **多选下载** — 勾选歌曲批量下载 MP3 + LRC 歌词
- 📝 **文件日志** — 所有操作记录到 `logs/` 目录，按天分文件

## 下载

从 [Releases](https://github.com/weget-world/netease-downloader/releases) 页面下载最新版 `网易云音乐下载器-GUI.exe`，双击即可运行。

## 使用

1. 在搜索框输入关键词，点击「搜索」
2. 浏览结果列表，勾选想下载的歌曲
3. 点击「下载选中」开始下载
4. 下载的文件在程序同目录的 `downloads/` 文件夹下
5. 点击「日志」按钮查看运行记录

## 截图

![截图](screenshot.png)

## 从源码运行

需要 Python 3.10+：

```bash
pip install requests mutagen pymusiclibrary
python netease_gui.py
```

## 打包

```bash
pyinstaller --onefile --windowed --name 网易云音乐下载器-GUI ^
  --add-data "<site-packages>\\MusicLibrary\\lib;MusicLibrary\\lib" ^
  --add-data "<site-packages>\\MusicLibrary\\*.py;MusicLibrary" ^
  --hidden-import MusicLibrary.neteaseCloudMusicApi ^
  --hidden-import MusicLibrary.core ^
  --hidden-import MusicLibrary.init ^
  --hidden-import MusicLibrary.common ^
  netease_gui.py
```

## 技术栈

- Python 3 + tkinter（GUI）
- pymusiclibrary（网易云 API 加密）
- requests（HTTP 下载）
- PyInstaller（打包分发）

## License

MIT
