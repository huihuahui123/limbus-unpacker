#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
边狱巴士解包器 —— Limbus Company (PJSH) 资源解包工具
======================================================

作者 / Author : 得捕牢勒
版本 / Version: v1.0

覆盖两类资源来源（缺一不可）：
  1. 游戏安装目录      —— 内置 .assets / .bundle / FMOD .bank
  2. Addressables 缓存 —— %LOCALAPPDATA%Low\\Unity\\ProjectMoon_LimbusCompany\\<hash>\\<hash>\\__data
     (进游戏后下载的资源，安装目录里没有，例如抽卡立绘)

用法见 README.md。典型：
    python lcb_unpack.py --all
    python lcb_unpack.py --filter gacha
    python lcb_unpack.py --only images --limit 20
"""

import argparse
import csv
import io
import json
import multiprocessing
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import traceback

# ---------------------------------------------------------------- 工具信息
# 注意：游戏文件夹名是 APP_NAME，工具显示名是这个 TOOL_NAME，两者不冲突
TOOL_NAME = "边狱巴士解包器"
TOOL_NAME_EN = "Limbus Company Resource Unpacker"
AUTHOR = "得捕牢勒"
TOOL_VERSION = "v1.0"

from concurrent.futures import ProcessPoolExecutor, as_completed

# Windows 控制台默认 GBK，中文菜单会乱码；统一切成 UTF-8
if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ---------------------------------------------------------------- 常量

# 游戏文件夹名（Steam 库文件名），不是工具名
APP_NAME = "LimbusCompany"
STEAM_CANDIDATES = [
    r"E:\Program Files (x86)\Steam\steamapps\common\Limbus Company",
    r"D:\Program Files (x86)\Steam\steamapps\common\Limbus Company",
    r"C:\Program Files (x86)\Steam\steamapps\common\Limbus Company",
]

# Unity 6。缓存里的 bundle 没有版本头，必须显式指定，否则 UnityPy 报
# "No valid Unity version found"
FALLBACK_UNITY_VERSION = "6000.3.12f1"

# 默认导出的对象类型
DEFAULT_TYPES = {
    "Texture2D", "Sprite", "AudioClip", "TextAsset", "Font",
    "Mesh", "Material", "AnimationClip",
}

ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')
NON_ASCII_SAFE = True  # 文件名强制 ASCII（防外部工具/韩文名中断）


# ---------------------------------------------------------------- 工具函数

def sanitize(name, maxlen=120):
    """把 Unity 对象名转成合法文件名。非 ASCII 保留（Python 可写），但剔除控制字符。"""
    if not name:
        return "unnamed"
    name = ILLEGAL.sub("_", str(name)).strip().strip(".")
    if not name:
        return "unnamed"
    return name[:maxlen]


WIN_BAD = '\\/:*?"<>|'


def ascii_name(name):
    """压成纯 ASCII 且不含 Windows 非法字符（'|' 等会导致 Errno 22）"""
    out = "".join(
        c if (32 <= ord(c) < 127 and c not in WIN_BAD) else "_"
        for c in str(name))
    out = out.strip("._ ")
    return out or "unnamed"


def ensure_dir(d):
    """多进程并发建目录会偶发 PermissionError，重试几次"""
    for i in range(6):
        try:
            os.makedirs(d, exist_ok=True)
            return True
        except Exception:
            time.sleep(0.05 * (i + 1))
    return False


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "{:.1f}{}".format(n, u)
        n /= 1024.0
    return "{:.1f}TB".format(n)


def fmt_dur(s):
    s = int(max(0, s))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return "{:d}:{:02d}:{:02d}".format(h, m, s) if h else "{:02d}:{:02d}".format(m, s)


def render_progress(done, total, done_bytes, total_bytes, items, t0, last=False):
    """
    进度条。按"已处理字节数"计算更贴近真实耗时——文件大小差异可达千倍，
    按文件数算会一路卡在 99%。
    输出被重定向到文件时自动降级为普通日志行（避免刷屏）。
    """
    if total_bytes > 0:
        frac = done_bytes / float(total_bytes)
    else:
        frac = done / float(total) if total else 0.0
    frac = min(1.0, max(0.0, frac))
    el = time.time() - t0
    eta = (el / frac - el) if frac > 0.005 else 0.0

    if not sys.stdout.isatty():          # 重定向/管道：不刷新进度条
        if last or done % 10 == 0 or done == total:
            print("  进度 {}/{}  {:.0f}%  已导出 {} 项  {}s".format(
                done, total, frac * 100, items, int(el)), flush=True)
        return

    W = 28
    f = int(W * frac)
    bar = "█" * f + "·" * (W - f)
    sys.stdout.write(
        "\r  [{}] {:>5.1f}%  {}/{}  已导出 {} 项  用时 {}  剩余约 {}   ".format(
            bar, frac * 100, done, total, items, fmt_dur(el), fmt_dur(eta)))
    sys.stdout.flush()
    if last:
        sys.stdout.write("\n")
        sys.stdout.flush()


# ---------------------------------------------------------------- 路径发现

def find_game_root(cli_root):
    """找不到时返回 None（不退出）—— 换电脑时可能只装了缓存没装游戏"""
    if cli_root:
        if not os.path.isdir(cli_root):
            sys.exit("[错误] 指定的游戏目录不存在: {}".format(cli_root))
        return cli_root
    for c in STEAM_CANDIDATES:
        if os.path.isdir(c):
            return c
    # 扫一遍常见盘符（含非系统盘与自定义 Steam 库）
    for drive in "CDEFGHIJKLMN":
        for lib in ("Program Files (x86)", "Program Files", "", "SteamLibrary",
                    "Games\\Steam", "Steam"):
            base = "{}:\\{}".format(drive, lib) if lib else "{}:\\".format(drive)
            p = os.path.join(base, "Steam", "steamapps", "common", APP_NAME)
            if os.path.isdir(p):
                return p
            p2 = os.path.join(base, "steamapps", "common", APP_NAME)
            if os.path.isdir(p2):
                return p2
    return None


def default_output():
    """
    可移植的输出目录：优先"程序所在盘/目录"，避免写死 E 盘。
    无写权限时退回当前用户的 Downloads。
    """
    if getattr(sys, "frozen", False):          # 打包成 exe
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:                                       # 源码运行
        base = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.join(base, "LCB_Unpacked")
    try:
        if os.access(base, os.W_OK):
            return cand
    except Exception:
        pass
    home = os.path.expanduser("~")
    return os.path.join(home, "Downloads", "LCB_Unpacked")


def read_unity_version(game_root):
    """从 globalgamemanagers 读引擎版本，失败则用内置兜底版本"""
    if not game_root:
        return FALLBACK_UNITY_VERSION
    p = os.path.join(game_root, "LimbusCompany_Data", "globalgamemanagers")
    try:
        with open(p, "rb") as f:
            head = f.read(4096)
        m = re.search(rb"(\d+\.\d+\.\d+[abfp]\d+)", head)
        if m:
            return m.group(1).decode()
    except Exception:
        pass
    return FALLBACK_UNITY_VERSION


def find_addressables_cache():
    """运行期下载的资源缓存（15G 级别）"""
    low = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    lowlow = os.path.join(os.path.dirname(low), "LocalLow")
    base = os.path.join(lowlow, "Unity", "ProjectMoon_" + APP_NAME)
    return base if os.path.isdir(base) else None


# ---------------------------------------------------------------- catalog 解析

def build_bundle_name_map(catalog_path):
    """
    从 Addressables catalog.bin 提取 <32位hash> -> <可读前缀>
    bundle 文件名形如：gacha_11_assets_all_<32hex>.bundle
    """
    m = {}
    try:
        with open(catalog_path, "rb") as f:
            data = f.read()
    except Exception:
        return m
    for mm in re.finditer(rb"([A-Za-z0-9_\-]{2,120})_assets_all_([0-9a-fA-F]{32})\.bundle", data):
        prefix = mm.group(1).decode("utf-8", "ignore")
        h = mm.group(2).decode().lower()
        m.setdefault(h, prefix)
    return m


# ---------------------------------------------------------------- 输入文件枚举

def is_asset_file(path):
    n = os.path.basename(path)
    if n.startswith("."):
        return False
    low = n.lower()
    if ".split" in low:          # .assets.split0 等，由主文件带出
        return False
    # .bank 是 FMOD 音频容器，UnityPy 读不了，但里面有 FSB5 样本
    return (low.endswith(".assets") or low.endswith(".bundle")
            or low.endswith(".bank") or n == "__data")


def enum_inputs(game_root, cache_root, name_map, filt, limit):
    """返回 [(origin, path, label)]，label 是可读名，便于 --filter 命中缓存资源"""
    jobs = []

    # 1) 游戏安装目录（可能不存在）
    bases = []
    if game_root:
        data_dir = os.path.join(game_root, "LimbusCompany_Data")
        if os.path.isdir(data_dir):
            bases.append(data_dir)
        bases.append(game_root)
    for base in bases:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if not is_asset_file(os.path.join(root, f)):
                    continue
                p = os.path.join(root, f)
                label = re.sub(r"\.(assets|bundle|bank)$", "", f)
                jobs.append(("game", p, label))

    # 2) Addressables 缓存：<hash>/<hash>/__data
    if cache_root and os.path.isdir(cache_root):
        for h1 in sorted(os.listdir(cache_root)):
            d1 = os.path.join(cache_root, h1)
            if not os.path.isdir(d1):
                continue
            for h2 in sorted(os.listdir(d1)):
                d2 = os.path.join(d1, h2)
                if not os.path.isdir(d2):
                    continue
                p = os.path.join(d2, "__data")
                if os.path.isfile(p):
                    # 缓存目录名可能是完整 hash 或前 N 位
                    label = None
                    for cand in (h1, h2):
                        if cand in name_map:
                            label = name_map[cand]
                        else:
                            for hk, v in name_map.items():
                                if hk.startswith(cand) or cand.startswith(hk):
                                    label = v
                                    break
                        if label:
                            break
                    jobs.append(("cache", p, label or h1[:12]))

    if filt:
        k = filt.lower()
        jobs = [j for j in jobs if k in j[1].lower() or k in j[2].lower()]

    # limit 先按枚举顺序截取（前 N 个更有代表性），
    # 再按文件大小升序排——让小文件先跑，进度条起步更快。
    if limit:
        jobs = jobs[:limit]
    jobs.sort(key=lambda x: os.path.getsize(x[1]) if os.path.exists(x[1]) else 0)
    return jobs


# ---------------------------------------------------------------- FSB5 处理

def fsb5_chunks(data):
    """
    在 FMOD bank 里切出内嵌的 FSB5 块。
    长度 = 0x3C + sampleHeaderSize + nameTableSize + dataSize
    """
    out = []
    pos = 0
    while True:
        i = data.find(b"FSB5", pos)
        if i < 0:
            break
        try:
            ver, ns, sh, nt, ds = struct.unpack_from("<5I", data, i + 4)
            total = 0x3C + sh + nt + ds
            if ver != 1 or ns == 0 or ns > 20000 or total <= 0 or total > len(data) - i + 64:
                pos = i + 4
                continue
            end = min(i + total, len(data))
            out.append((i, end, ns, sh, nt))
            pos = end
        except Exception:
            pos = i + 4
    return out


def rewrite_fsb_names(blob, ns, sh, nt):
    """
    把 FSB5 名字表改成纯 ASCII（等长替换，偏移不变）。
    韩文样本名会让 fsb_aud_extr.exe 静默中断，必须处理。
    返回 (新blob, 原名列表)
    """
    nt_start = 0x3C + sh
    if nt <= 0:
        return blob, []
    tbl = blob[nt_start:nt_start + nt]
    offsets = []
    for k in range(ns):
        if 4 * k + 4 > len(tbl):
            break
        offsets.append(struct.unpack_from("<I", tbl, 4 * k)[0])

    names = []
    newtbl = bytearray(tbl)
    for k, off in enumerate(offsets):
        if off >= len(tbl):
            names.append("")
            continue
        end = tbl.find(b"\x00", off)
        if end < 0:
            end = len(tbl)
        raw = tbl[off:end]
        orig = raw.decode("utf-8", "ignore")
        names.append(orig)
        # 等长 ASCII 替换
        L = len(raw)
        if L <= 0:
            continue
        # 统一成 s00001 这种短名（后面用 null 填充），转换后再按原名重命名
        cand = "s{:05d}".format(k + 1) if L >= 6 else (
            ("s%0*d" % (L - 1, k + 1)) if L > 1 else "a")
        repl = cand.encode("ascii", "ignore")[:L].ljust(L, b"\x00")
        newtbl[off:off + L] = repl

    out = bytearray(blob)
    out[nt_start:nt_start + nt] = newtbl
    return bytes(out), names


# ---------------------------------------------------------------- 单文件解包

def unpack_one(job):
    """
    job = (origin, path, label, out_root, types, version, audio_tool, do_fmod)
    返回 (rows, errors)
    """
    import UnityPy
    from UnityPy import config as _cfg

    origin, path, label, out_root, types, version, audio_tool, do_fmod = job
    _cfg.FALLBACK_UNITY_VERSION = version

    rows, errors = [], []

    def out_dir(kind):
        return os.path.join(out_root, kind, sanitize(label))

    def save(rel_dir, fname, payload, kind, otype, oname):
        d = os.path.join(out_root, rel_dir, sanitize(label))
        if not ensure_dir(d):
            errors.append("{}: 无法创建目录 {}".format(path, d))
            return None
        p = os.path.join(d, fname)
        if os.path.exists(p):                     # 续跑：已存在就跳过
            return p
        # 杀软实时扫描会瞬时锁住刚创建的文件，重试几次即可
        last = None
        for i in range(5):
            try:
                with open(p, "wb") as f:
                    f.write(payload)
                rows.append({"origin": origin, "source": path, "type": otype,
                             "object": oname, "output": os.path.relpath(p, out_root),
                             "size": len(payload)})
                return p
            except Exception as e:
                last = e
                time.sleep(0.08 * (i + 1))
        errors.append("{} [{}] 写入失败 {}".format(path, otype, last))
        return None

    # .bank 不是 Unity 序列化文件，加载必失败；失败不阻断，继续走 FMOD 分支
    env = None
    try:
        env = UnityPy.load(path)
    except Exception as e:
        if not path.lower().endswith(".bank"):
            errors.append("{}: 加载失败 {}".format(path, e))

    for obj in (env.objects if env is not None else []):
        tname = obj.type.name
        try:
            if tname == "Texture2D" and "Texture2D" in types:
                d = obj.read()
                img = getattr(d, "image", None)
                if img is None:
                    continue
                name = ascii_name(getattr(d, "m_Name", None) or obj.path_id)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                save("Images", "{}.png".format(name), buf.getvalue(),
                     "Texture2D", tname, name)

            elif tname == "Sprite" and "Sprite" in types:
                d = obj.read()
                img = getattr(d, "image", None)
                if img is None:
                    continue
                name = ascii_name(getattr(d, "m_Name", None) or obj.path_id)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                save("Images", "{}.png".format(name), buf.getvalue(),
                     "Sprite", tname, name)

            elif tname == "AudioClip" and "AudioClip" in types:
                d = obj.read()
                samples = getattr(d, "samples", None) or {}
                nm = ascii_name(getattr(d, "m_Name", None) or obj.path_id)
                for sn, data in samples.items():
                    ext = "ogg" if data[:4] == b"OggS" else (
                        "wav" if data[:4] == b"RIFF" else "bin")
                    save("Audio", "{}_{}.{}".format(nm, ascii_name(sn), ext),
                         data, "AudioClip", tname, nm)

            elif tname == "TextAsset" and "TextAsset" in types:
                d = obj.read()
                raw = getattr(d, "script", None)
                if raw is None:
                    continue
                if isinstance(raw, str):
                    raw = raw.encode("utf-8", "ignore")
                nm = ascii_name(getattr(d, "m_Name", None) or obj.path_id)
                ext = "bytes"
                if raw[:4] == b"RIFF" or b"FSB5" in raw[:4096]:
                    ext = "fsb"
                elif raw[:1] in (b"{", b"["):
                    ext = "json"
                save("Text", "{}.{}".format(nm, ext), raw, "Text", tname, nm)

            elif tname == "Font" and "Font" in types:
                d = obj.read()
                data = getattr(d, "font", None) or getattr(d, "raw_data", None)
                if not data:
                    continue
                nm = ascii_name(getattr(d, "m_Name", None) or obj.path_id)
                ext = "ttf" if data[:4] in (b"\x00\x01\x00\x00", b"true") else "otf"
                save("Fonts", "{}.{}".format(nm, ext), data, "Fonts", tname, nm)

            elif tname == "Mesh" and "Mesh" in types:
                d = obj.read()
                nm = ascii_name(getattr(d, "m_Name", None) or obj.path_id)
                try:
                    data = d.export().encode("utf-8")
                    save("Models", "{}.obj".format(nm), data, "Models", tname, nm)
                except Exception:
                    pass

            elif tname in ("Material", "AnimationClip") and tname in types:
                try:
                    tree = obj.read_typetree()
                except Exception:
                    continue
                nm = ascii_name(tree.get("m_Name") or obj.path_id)
                payload = json.dumps(tree, ensure_ascii=False, indent=1).encode("utf-8")
                save("Metadata", "{}.{}.json".format(nm, tname),
                     payload, "Metadata", tname, nm)

        except Exception as e:
            errors.append("{} [{}] {}".format(path, tname, e))

    # FMOD bank：切 FSB5（UnityPy 读不了 .bank，直接二进制处理）
    if do_fmod and path.lower().endswith(".bank"):
        try:
            with open(path, "rb") as f:
                blob = f.read()
            for (s, e, ns, sh, nt) in fsb5_chunks(blob):
                chunk = blob[s:e]
                fixed, names = rewrite_fsb_names(chunk, ns, sh, nt)
                tag = "{}_{}_{}samples".format(label, len(rows), ns)
                d = os.path.join(out_root, "Audio", "_fsb", sanitize(label))
                if not ensure_dir(d):
                    errors.append("{}: 无法创建目录 {}".format(path, d))
                    continue
                fp = os.path.join(d, "{}.fsb".format(ascii_name(tag)))
                for _try in range(6):          # 并发写偶发 PermissionError
                    try:
                        with open(fp, "wb") as f:
                            f.write(fixed)
                        break
                    except Exception:
                        time.sleep(0.05 * (_try + 1))
                with open(fp[:-4] + ".names.json", "w", encoding="utf-8") as f:
                    json.dump({"total": ns, "order": names}, f, ensure_ascii=False, indent=1)
                rows.append({"origin": origin, "source": path, "type": "FSB5",
                             "object": tag, "output": os.path.relpath(fp, out_root),
                             "size": len(fixed)})
                # 可选：调用 fsb_aud_extr.exe 转 wav
                if audio_tool and os.path.isfile(audio_tool):
                    try:
                        td = os.path.dirname(audio_tool)
                        # 工具依赖同目录的 fmodex.dll，拷到输出目录再就地运行，
                        # 保证 wav 落在我们的输出目录而不是工具目录
                        for dll in ("fmodex.dll", "fmodL.dll", "fmod.dll"):
                            s = os.path.join(td, dll)
                            if os.path.isfile(s) and not os.path.isfile(os.path.join(d, dll)):
                                shutil.copy2(s, os.path.join(d, dll))
                        subprocess.run([audio_tool, os.path.basename(fp)],
                                       cwd=d, timeout=3600,
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
                        # 转换后按 FSB 内的原始名字重命名（还原韩文名等）
                        for i, orig in enumerate(names, 1):
                            s = os.path.join(d, "s{:05d}.wav".format(i))
                            if not os.path.isfile(s):
                                continue
                            base = sanitize((orig or "").strip()
                                            or "sample{:05d}".format(i))
                            t = os.path.join(d, base + ".wav")
                            if t != s:
                                try:
                                    if not os.path.exists(t):
                                        os.rename(s, t)
                                    else:
                                        t = s
                                except Exception:
                                    t = s
                            try:
                                rows.append({
                                    "origin": origin, "source": path,
                                    "type": "AudioClip(wav)", "object": base,
                                    "output": os.path.relpath(t, out_root),
                                    "size": os.path.getsize(t)})
                            except Exception:
                                pass
                    except Exception as e:
                        errors.append("{} [wav] {}".format(path, e))
        except Exception as e:
            errors.append("{} [FMOD] {}".format(path, e))

    return rows, errors


# ---------------------------------------------------------------- 主流程

def build_parser():
    ap = argparse.ArgumentParser(
        description="{} ({})  作者: {}  {}".format(
            TOOL_NAME, TOOL_NAME_EN, AUTHOR, TOOL_VERSION),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="直接不带参数运行可进入中文菜单。")
    ap.add_argument("--game", help="游戏安装目录（默认自动探测 Steam 路径）")
    ap.add_argument("--out", default=None,
                    help="输出目录（默认：程序所在目录下的 LCB_Unpacked）")
    ap.add_argument("--only", default="all",
                    choices=["all", "images", "audio", "text", "metadata"],
                    help="只解包某一类资源")
    ap.add_argument("--filter", help="只处理路径含此关键词的文件，如 gacha")
    ap.add_argument("--limit", type=int, help="最多处理 N 个文件（测试用）")
    ap.add_argument("--jobs", type=int, default=4, help="并行进程数，默认 4")
    ap.add_argument("--no-cache", action="store_true", help="跳过 Addressables 缓存目录")
    ap.add_argument("--no-fmod", action="store_true", help="跳过 FMOD bank 音频")
    ap.add_argument("--audio-tool", help="fsb_aud_extr.exe 路径（用于 .fsb 转 wav）")
    ap.add_argument("--unity-version", help="手动覆盖 Unity 版本")
    ap.add_argument("--list", action="store_true", help="只列出待处理文件，不实际解包")
    return ap


def default_args():
    """菜单模式下补齐的参数默认值（out=None → 运行时按当前电脑算出可移植路径）"""
    return argparse.Namespace(
        game=None, out=None, only="all",
        filter=None, limit=None, jobs=4, no_cache=False,
        no_fmod=False, audio_tool=None, unity_version=None, list=False)


def interactive_menu(game_root, cache_root, version):
    """无命令行参数时的中文交互菜单"""
    print("=" * 62)
    print("  {}  {}".format(TOOL_NAME, TOOL_VERSION))
    print("  {}  作者: {}".format(TOOL_NAME_EN, AUTHOR))
    print("=" * 62)
    print("  游戏目录 : {}".format(game_root or "(未找到，将只解缓存资源)"))
    print("  缓存目录 : {}".format(cache_root or "(未找到，将只解安装目录)"))
    print("  Unity    : {}".format(version))
    print("  输出目录 : {}".format(default_output()))
    print("-" * 62)
    print("  [1] 全量解包   图片 + 音频 + 文本 + 元数据（耗时长）")
    print("  [2] 仅图片     贴图与精灵，速度较快")
    print("  [3] 仅音频     AudioClip + FMOD bank")
    print("  [4] 仅文本     脚本、配置、数据表")
    print("  [5] 关键词过滤  只解名字含关键词的文件（如 gacha）")
    print("  [6] 只列文件   预览会解哪些，不实际解包")
    print("  [0] 退出")
    print("-" * 62)

    try:
        c = input("  请输入序号并回车: ").strip()
    except EOFError:
        return None

    a = default_args()
    if c == "1":
        print()
        print("  [!] 全量解包会处理安装目录 + 缓存目录共约 26 GB，")
        print("      可能持续数小时并占用几十 GB 磁盘空间。")
        print("      建议先用 [2] 或 [5] 小范围试跑。")
        try:
            ok = input("      确认继续请输入 y，回车取消: ").strip().lower()
        except EOFError:
            ok = ""
        if ok != "y":
            print("  已取消。")
            return None
        a.only = "all"
    elif c == "2":
        a.only = "images"
    elif c == "3":
        a.only = "audio"
    elif c == "4":
        a.only = "text"
    elif c == "5":
        try:
            kw = input("  请输入关键词（如 gacha / SFX / BGM）: ").strip()
        except EOFError:
            return None
        if not kw:
            print("  未输入关键词，已取消。")
            return None
        a.filter = kw
    elif c == "6":
        a.list = True
        try:
            kw = input("  关键词（直接回车 = 全部）: ").strip()
        except EOFError:
            kw = ""
        a.filter = kw or None
    else:
        print("  已退出。")
        return None

    # 可选的附加设置
    try:
        more = input("  附加设置：输出目录 / 并行数 / 限制数量（直接回车用默认）: ").strip()
    except EOFError:
        more = ""
    if more:
        parts = more.replace("，", ",").split(",")
        for seg in parts:
            seg = seg.strip()
            if not seg:
                continue
            if re.match(r"^\d+$", seg):                  # 纯数字 = 限制文件数
                a.limit = int(seg)
            elif seg.lower().startswith("j"):            # j8 = 并行 8
                a.jobs = int(re.sub(r"\D", "", seg) or 4)
            else:                                        # 其余当输出目录
                a.out = seg.strip('"')
    print()
    return a


def main():
    # PyInstaller 打包后的子进程必须调用，否则多进程会重复启动
    multiprocessing.freeze_support()

    ap = build_parser()
    if len(sys.argv) == 1:
        # 无参数 → 交互菜单（命令行模式下保持 args 结构一致）
        game_root = find_game_root(None)
        version = read_unity_version(game_root)
        cache_root = find_addressables_cache()
        args = interactive_menu(game_root, cache_root, version)
        if args is None:
            return
    else:
        args = ap.parse_args()

    if args.only == "all":
        types = DEFAULT_TYPES
    elif args.only == "images":
        types = {"Texture2D", "Sprite"}
    elif args.only == "audio":
        types = {"AudioClip"}
    elif args.only == "text":
        types = {"TextAsset"}
    else:
        types = {"Material", "AnimationClip"}

    game_root = find_game_root(args.game)
    version = args.unity_version or read_unity_version(game_root)
    cache_root = None if args.no_cache else find_addressables_cache()
    out = args.out or default_output()

    print("=" * 62)
    print(" {}  {}".format(TOOL_NAME, TOOL_VERSION))
    print(" {}  作者: {}".format(TOOL_NAME_EN, AUTHOR))
    print("=" * 62)
    print(" 游戏目录 : {}".format(game_root or "(未找到，将只解缓存；可用 --game 指定)"))
    print(" 缓存目录 : {}".format(cache_root or "(未找到/已跳过)"))
    print(" Unity    : {}".format(version))
    print(" 输出     : {}".format(out))
    print(" 类型     : {}".format(", ".join(sorted(types))))
    print("-" * 62)

    if not game_root and not cache_root:
        print(" 既未找到游戏目录，也未找到资源缓存，无法继续。")
        print(" 请用 --game 指定游戏安装目录，或确认这台电脑上运行过游戏。")
        return

    name_map = {}
    if game_root:
        cat = os.path.join(game_root, "LimbusCompany_Data", "StreamingAssets", "aa", "catalog.bin")
        if os.path.isfile(cat):
            name_map = build_bundle_name_map(cat)
            print(" catalog  : 解析到 {} 个 bundle 名映射".format(len(name_map)))

    jobs_src = enum_inputs(game_root, cache_root, name_map, args.filter, args.limit)
    total_bytes = sum(os.path.getsize(p) for _, p, _ in jobs_src if os.path.exists(p))
    print(" 待处理   : {} 个文件，共 {}".format(len(jobs_src), human(total_bytes)))
    print("-" * 62)

    if not jobs_src:
        print("没有匹配的文件，退出。")
        return

    if args.list:
        for o, p, lb in jobs_src:
            print("  [{}] {:30s} {:>8s}  {}".format(
                o, lb, human(os.path.getsize(p)), p[:90]))
        print("\n共 {} 个文件（--list 模式，未解包）".format(len(jobs_src)))
        return

    os.makedirs(out, exist_ok=True)
    jobs = [(o, p, lb, out, types, version,
             args.audio_tool, not args.no_fmod) for o, p, lb in jobs_src]

    sizes = [os.path.getsize(p) if os.path.exists(p) else 0
             for _, p, _ in jobs_src]
    all_rows, all_errs = [], []
    t0 = time.time()
    done = 0
    done_bytes = 0
    nproc = max(1, min(args.jobs, len(jobs)))

    with ProcessPoolExecutor(max_workers=nproc) as ex:
        futs = {ex.submit(unpack_one, j): sz for j, sz in zip(jobs, sizes)}
        for fu in as_completed(futs):
            done += 1
            done_bytes += futs[fu]
            try:
                rows, errs = fu.result()
                all_rows.extend(rows)
                all_errs.extend(errs)
            except Exception as e:
                all_errs.append("worker 异常: {}".format(e))
            render_progress(done, len(jobs), done_bytes, total_bytes,
                            len(all_rows), t0, last=(done == len(jobs)))

    # 清单
    mf = os.path.join(out, "_manifest.csv")
    with io.open(mf, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["origin", "source", "type", "object", "output", "size"])
        w.writeheader()
        w.writerows(all_rows)

    if all_errs:
        with io.open(os.path.join(out, "_errors.log"), "w", encoding="utf-8") as f:
            f.write("\n".join(all_errs[:5000]))

    print("-" * 62)
    print(" 完成：导出 {} 项，用时 {:.0f}s".format(len(all_rows), time.time() - t0))
    print(" 清单：{}".format(mf))
    if all_errs:
        print(" 错误：{} 条（详见 _errors.log）".format(len(all_errs)))
    print("-" * 62)
    print(" {}  {}  作者: {}".format(TOOL_NAME, TOOL_VERSION, AUTHOR))
    print("=" * 62)


if __name__ == "__main__":
    main()
