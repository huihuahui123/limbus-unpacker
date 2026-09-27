# 边狱巴士解包器（Limbus Company Resource Unpacker）

把游戏里的图片、音频、文本、字体、模型全部解出来，自动覆盖**两个资源来源**。

| 项目 | 值 |
|---|---|
| 工具名 | 边狱巴士解包器 |
| 原文名 | Limbus Company Resource Unpacker |
| 版本 | v1.0 |
| **作者 / 署名** | **得捕牢勒** |

**全程只读游戏目录，不会修改或删除任何游戏文件。**

---

## 一、最快上手（不需要装 Python）

双击 **`边狱巴士解包器.exe`**，中文菜单自己弹出来，按数字键选就行。

> exe 约 22 MB，首次启动会解压到临时目录，慢 1~2 秒属正常。
> 若杀软误报，选"允许运行"即可（PyInstaller 打包的普通控制台程序）。

---

## 二、菜单每一项是什么意思

```
  [1] 全量解包   图片 + 音频 + 文本 + 元数据（耗时长）
  [2] 仅图片     贴图与精灵，速度较快
  [3] 仅音频     AudioClip + FMOD bank
  [4] 仅文本     脚本、配置、数据表
  [5] 关键词过滤  只解名字含关键词的文件（如 gacha）
  [6] 只列文件   预览会解哪些，不实际解包
  [0] 退出
```

| 选项 | 含义 | 什么时候用 |
|---|---|---|
| **1 全量解包** | 两处来源、所有类型全解 | 想一次拿全。约 26 GB 输入，可能跑几小时，会占几十 GB。**选它会二次确认** |
| **2 仅图片** | 只导 Texture2D + Sprite → PNG | 找立绘、UI、图标。最快，第一次建议先跑它 |
| **3 仅音频** | AudioClip + FMOD `.bank`（切成 FSB） | 找 BGM、音效 |
| **4 仅文本** | TextAsset → txt / json / bytes | 找配置表、脚本 |
| **5 关键词过滤** | 只解路径或资源名含关键词的文件 | 精准定向，如 `gacha`、`SFX_1`、`BGM` |
| **6 只列文件** | 列出会处理哪些文件及大小，**不写硬盘** | 不确定关键词对不对，先预览 |

选 1~5 之后还会问一次"附加设置"，**直接回车 = 全部默认**：

- 填**纯数字** → 限制处理文件数量（如 `20`，先试跑 20 个）
- 填 `j8` → 并行进程数改成 8
- 填**路径** → 改输出目录（如 `D:\LCB_out`）
- 多个用逗号隔开：`D:\LCB_out,20,j8`

默认输出目录：exe 所在目录下的 `LCB_Unpacked`（不写死盘符，换电脑也能用）

---

## 三、命令行用法（可选）

exe 与 `lcb_unpack.py` 参数完全一致：

```bash
边狱巴士解包器.exe                          # 不带参数 = 进菜单
边狱巴士解包器.exe --only images            # 只要图片
边狱巴士解包器.exe --filter gacha           # 只解抽卡相关
边狱巴士解包器.exe --filter gacha --list    # 只预览，不实际解包
边狱巴士解包器.exe --only images --limit 20 # 先试跑 20 个小文件
边狱巴士解包器.exe --out D:\LCB_out --jobs 8
```

| 参数 | 说明 |
|---|---|
| `--game` | 手动指定游戏目录（默认自动探测 Steam 路径） |
| `--out` | 输出目录，默认 exe 同级目录下的 `LCB_Unpacked` |
| `--only` | `all` / `images` / `audio` / `text` / `metadata` |
| `--filter` | 只处理路径或资源名含该关键词的文件 |
| `--limit N` | 最多处理 N 个文件（测试用） |
| `--jobs N` | 并行进程数，默认 4 |
| `--audio-tool` | `fsb_aud_extr.exe` 路径，音频自动转 wav |
| `--no-cache` | 跳过 Addressables 缓存（只解安装目录） |
| `--no-fmod` | 跳过 FMOD bank 音频 |
| `--list` | 只列文件不解包 |

**支持续跑**：中断后直接重跑，已导出的文件会自动跳过。

---

## 四、输出结构

```
<输出目录>\
├─ Images\<资源包名>\*.png          贴图与精灵
├─ Audio\<资源包名>\*.wav|ogg       Unity 音频
├─ Audio\_fsb\<bank名>\*.fsb        FMOD 音频包（附 .names.json 原名映射）
├─ Text\<资源包名>\*.json|bytes     文本与配置
├─ Fonts\                           字体
├─ Models\                          Mesh（OBJ）
├─ Metadata\                        材质与动画（JSON）
├─ _manifest.csv                    全部条目索引（可反查来源路径）
└─ _errors.log                      失败明细（正常情况为空）
```

文件名中的来源标签是 Addressables 的真实资源名（如 `gachabanner_common01`），
由 `catalog.bin` 反查得到，覆盖率约 84%，查不到的用 hash 前 12 位。

---

## 五、进度显示

运行时会显示一条实时刷新的进度条：

```
  [██████████████████··········]  65.0%  120/200  已导出 840 项  用时 12:34  剩余约 06:46
```

- 百分比按**已处理字节数**算，不是文件数。文件体积能差上千倍，
  按文件数算会出现"卡在 99% 不动"的假象。
- 剩余时间是按当前速度估算的，仅供参考（大文件处理时会跳变）。
- 输出被重定向到文件/管道时会自动降级成普通日志行，不会刷屏。

## 六、在别的电脑上使用（可移植性）

**能。** 把 `边狱巴士解包器.exe` 单独拷到 U 盘或另一台电脑，双击就能跑，解出来的文件原样拷回来即可。

已经为跨机运行做过处理：

| 项目 | 处理方式 |
|---|---|
| Python 环境 | exe 自带，不需要安装 Python |
| 运行库 | `VCRUNTIME140.dll`、`MSVCP140.dll` 等已打包进去，无需装 VC++ 运行库 |
| 游戏目录 | 自动扫描 C~N 盘的常见 Steam 路径（含 `SteamLibrary`、自定义库）；找不到会提示，可用 `--game` 手动指定 |
| 资源缓存 | 按 `%LOCALAPPDATA%` 自动定位到**当前用户**的 `LocalLow\Unity\ProjectMoon_LimbusCompany` |
| Unity 版本 | 从游戏文件里自动读取，不同版本都能适配 |
| 输出目录 | **不再写死 E 盘**，默认是 exe 所在目录下的 `LCB_Unpacked`；该目录无写权限时自动改用当前用户的 `Downloads\LCB_Unpacked` |

注意两点：

1. **那台电脑必须装过游戏并进过游戏**。资源分两处（见下节），
   抽卡立绘、卡池横幅这类只在 `LocalLow` 缓存里，没跑过游戏就没有。
2. 若只找到缓存没找到游戏目录（比如便携版），工具会继续跑，只解缓存部分。

杀毒软件可能误报 PyInstaller 打包的 exe，选"允许运行"即可。

## 七、两个必须知道的点

### 1. 资源分两处，只看安装目录是不全的

| 位置 | 内容 |
|---|---|
| `Steam\steamapps\common\Limbus Company` | 内置资源（11 GB） |
| `%LOCALAPPDATA%Low\Unity\ProjectMoon_LimbusCompany` | 进游戏后下载的 Addressables 包（约 15 GB） |

抽卡立绘、卡池横幅这类**只在第二处**。工具两处都扫。
（注意：不是 `LocalLow\ProjectMoon\LimbusCompany\`，那里只有存档。）

### 2. 全量解包很慢很大

两处加起来约 26 GB，全量**可能输出几十 GB、跑数小时**。
建议先 `--only images --limit 20` 试跑，确认无误再全量。

---

## 八、工具内部已经处理掉的坑

这些都是实际踩过的，不用你再管：

- **Unity 6 版本头**：引擎 `6000.3.12f1`，缓存 bundle 没有版本头，必须显式指定，否则 UnityPy
  报 "No valid Unity version found"。工具自动从 `globalgamemanagers` 读版本，失败用内置兜底值。
- **缓存 bundle 命名**：缓存是 `<hash>/<hash>/__data`，光看目录名没法用。工具用 catalog
  把 hash 反查成可读名（如 `commongacharesource`、`manual_gacha`），覆盖率约 84%。
- **FMOD 音频不在 Unity 对象里**：UnityPy 读不了 `.bank`，工具直接按 `FSB5` 头切包，
  长度 = `0x3C + sampleHeaderSize + nameTableSize + dataSize`。
- **韩文样本名会让提取器静默中断**：`fsb_aud_extr.exe` 是 ANSI 程序，遇到韩文名会中途停止且不报错。
  工具先把 FSB 名字表重写为 ASCII，转完再按 `names.json` 改回原名。
- **文件名非法字符**：Unity 对象名常带 `|` 等 Windows 非法字符，直接写报 `Errno 22`，已过滤。
- **杀软实时扫描**：高速写入时文件被瞬时锁住报 `PermissionError`，已内置重试。

## 九、音频说明

- **Unity AudioClip**：直接导出 `.wav` / `.ogg`，无需外部工具。
- **FMOD bank（`.assets.bank`）**：先切出 `.fsb`，加 `--audio-tool` 可自动转 wav。
  没有该工具时保留 `.fsb` + `names.json`，可之后手动转换。

## 十、文件清单

| 文件 | 用途 |
|---|---|
| `边狱巴士解包器.exe` | 主程序，双击即用，**不需要 Python** |
| `边狱巴士解包器.bat` | 启动器（优先调 exe，没有就回退 Python 脚本） |
| `lcb_unpack.py` | 源码，可自行修改 |
| `重新打包.bat` | 改完源码重新生成 exe（需要 Python 环境） |
| `README.md` | 本说明 |

打包 exe 需要额外收集三个包的子模块与数据，否则会报
`No module named 'UnityPy.resources'` / 找不到 `fmod.dll` / 找不到
`archspec/.../microarchitectures.json`：

```
--collect-submodules UnityPy --collect-data UnityPy
--collect-submodules fmod_toolkit --collect-data fmod_toolkit
--collect-submodules archspec --collect-data archspec
```

另外打包后必须调用 `multiprocessing.freeze_support()`，否则 Windows 下多进程会重复启动。

---

---

## GitHub 开源须知

**本仓库只包含工具本身，不包含任何游戏素材。** 提交前请确认：

- 仓库里没有 `LCB_Unpacked/` 目录，也没有任何 PNG / wav / fsb / 配置表；
- `.gitignore` 已就位（本目录已包含）；
- 项目名不要带官方 / 项目组字样，避免商标与不正当竞争争议。

解出来的素材**版权归 Project Moon 所有**，仅供个人学习研究，
不得公开发布、二次分发或用于商业用途。工具全程只读游戏目录，不修改游戏文件。

---

由 **得捕牢勒** 制作 / Maintained by **DEBOILER**（得捕牢勒）。

解包所得素材版权归 Project Moon 所有，请个人学习研究使用。
