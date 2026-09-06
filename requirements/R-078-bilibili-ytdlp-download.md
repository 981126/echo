# R-078-BILIBILI-YTDLP-DOWNLOAD: B站视频/音频经 yt-dlp 直连下载（补 R-077 B站缺口）

- **日期**: 2026-09-06
- **提出渠道**: 对话（承接 R-077：TikHub B站播放流端点 `fetch_video_playurl` 等当前对当前 key 返回 404，B站下载悬空）
- **原文摘要**: 作者提到“有一个提供地址就可以在线下载各个自媒体平台视频的网站”，经澄清选择：把 yt-dlp 通道接进系统（不接第三方在线解析站），先拿 1-2 条真实 B站作品验证，再全量接入。
- **状态**: ✅ 已完成
- **排期**: M60（已完成）
- **关联**: R-077、PRD §3.2/§3.3、D-038、`media_ensure.py` / `media_downloader.py` / `tikhub.py`

## 背景
- R-077 已把「同步数据 → 缺视频下载 → 自动转写」接好；抖音/小红书真实下载通过。
- B站：TikHub `fetch_video_playurl`（bv_id+cid，返回 DASH video/audio）、`fetch_vip_video_playurl`、`fetch_one_video` 系列、`fetch_video_play_info` 线上均 404（API 市场未开通/服务端下线），故 B站作品当前提示「无可用视频源」。
- 作者在 TikHub API 市场看到了 `fetch_video_playurl` 页面（可能开通后可用），但当下先用 yt-dlp 补位（开源、B站强支持、可直连下视频/音频、普通画质免登录）。

## 方案
1. 依赖：backend 环境安装 `yt-dlp`（Docker 部署时同步加入镜像依赖；llm 等其余不动）。
2. 下载通道：B站在 `media_ensure._download_pick` 中，若 TikHub `fetch_video_source` 拿不到（当前 404）→ 回落 yt-dlp 直连下载：
   - 目标：低清完整 mp4（视频+音频，`bv*[height<=480]+ba/b`），供自动转写与本地留存；
   - 需要 ffmpeg 合并时用项目自带 imageio-ffmpeg；
   - 失败/风控/大会员独占：明确报「B站下载失败：原因」，不假下载。
3. 保持抖音/小红书走 TikHub 不变；TikHub B站接口若日后开通，仍优先 TikHub。
4. 先真实验证 1-2 条 B站作品（本机可直连 B站为前提）；NAS 部署时需放行 B站网络。

## 反问清单与结论
1. 范围：只补 B站一条 yt-dlp 下载通道；不接任何第三方在线解析网站。
2. 影响：B站素材卡「同步数据」从“提示无源”变为“可下载+自动转写”。
3. 数据/来源：直连 B站官方流（yt-dlp 解析），普通清晰度免登录；拿不到则明确失败原因。
4. 异常：网络不通/风控/需登录 → 单条失败提示，不影响其它平台；不编造文件。
5. 验收：1-2 条真实 B站作品能下出含音轨 mp4 并进入自动转写；verify.sh 全绿。
6. 成本：B站直连下载不消耗 TikHub 额度；占本机带宽/存储（低清可控）。
7. 依赖与风险：新增 yt-dlp 依赖；依赖运行环境能直连 B站（国内 NAS 一般可）。
8. 优先级：M60（作者已确认方向）。

## 原文（作者原话，未改动）
> 我记得有一个提供地址就可以在线下载各个自媒体平台视频的网站
> （澄清后选：2 接到系统里自动下载/转写，按 R-078 加 yt-dlp 通道，先真实验证再全量接）

## 实施结论（M60，2026-09-06）
1. 后端安装 `yt-dlp`（已加入 backend/requirements.txt；Docker 部署镜像需同步安装）。
2. B站下载回落已接入 `media_ensure._download_pick`：TikHub `fetch_video_source` 拿不到（当前 404）→ 用 yt-dlp 直连 B站下载 480P 视频 + m4a 音轨并 ffmpeg 合并为 mp4（含音轨，可直接自动转写）；失败重试一次，仍失败明确提示。
3. 账号可选：CreatorAccount.extra_config 里可放 `cookie`（B站 SESSDATA）增强稳定性（可选，不加也能下普通清晰度）。
4. 真实验证：用作者真实 B站作品 BV1Df421m7xF 下载成功（480P 视频 + m4a 音频 → mp4 14.9MB，含 Video+Audio）；B站瞬时风控 412 重试即通。
5. ffmpeg 复用项目自带 imageio-ffmpeg（运行时对二进制建标准名软链目录供 yt-dlp 识别）。
6. 自测：verify.sh 全绿；新增 3 个离线测试（B站回落/缺 BV 号报错/bvid 解析）。
