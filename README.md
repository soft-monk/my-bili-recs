# my-bili-recs —— 个人 B站视频推荐层

显式双轴打分（兴趣 / 价值）养出来的、只属于你自己的 B站视频推荐引擎。

- 设计文档：[docs/视频推荐想法整理.md](docs/视频推荐想法整理.md)（想法来源与调研）
- 实现方案：[docs/B站个人推荐层实现方案.md](docs/B站个人推荐层实现方案.md)（架构 / 算法 / 里程碑 / **优化项**）
- 优化清单：[docs/优化清单.md](docs/优化清单.md)（算法 / 界面 / 候选池 / 工程 / 安全，含落地批次）
- 油猴方案：[docs/油猴脚本与自动启停方案.md](docs/油猴脚本与自动启停方案.md)（页面打分 / 按需拉起 / 心跳自退）
- 需求文档：[docs/需求-推荐体验升级.md](docs/需求-推荐体验升级.md)（域外探索 / 两列布局 / 每日 10 赞 / 点赞列表）

## 核心思想

平台算法优化的是"平台要的时长"，不是"你想要的视频"。本项目把目标函数夺回来：
你给看过的视频打 **兴趣分**（我喜不喜欢）和 **价值分**（值不值得看），本地模型学出双轴原型，
对候选视频先过滤垃圾、再按口味排序。

## 当前进度

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| M1 | CLI 打分 + TF-IDF 双轴推荐闭环 | ✅ 完成 |
| M2 | B站候选池：分区排行榜自动收集（订阅源待登录 cookie） | ✅ 完成 |
| M3 | 油猴脚本在 B站页面一键双轴打分 | 计划中 |
| M4 | 每日清单网页 + 三档反馈 + 为什么推荐 + 探索位 ✅ / 页内重排 / 推送 / 评估统计 | 进行中 |

## 安装

```powershell
git clone https://github.com/soft-monk/my-bili-recs.git
cd my-bili-recs
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 如果 pip 报 `ProxyError`：本机系统代理（IE 代理）会破坏 Python 的网络。
> 先执行 `$env:NO_PROXY="*"` 再重试安装；换清华镜像也是常用解法。

## 每日循环（一次学会，之后每天 30 秒）

```powershell
# 1. 拉新候选：8 个分区排行榜各取 top 30（无需登录，自动排除已打分视频）
python collector.py --top 30

# 2. 打开每日精选网页（自动弹出浏览器，默认 http://127.0.0.1:8765/）
python serve.py

# 3. 点卡片标题去 B站看视频，看完回网页点「喜欢 / 无感 / 踩雷」（可撤销）
#    → 分数自动回写 data/scores.csv；清单当天固定不变，次日自动重算
#    → 想立刻换一批：点页面上的「重算今日清单」
```

## 打分（训练数据的来源）

```powershell
# CLI 打分：兴趣分 + 价值分 各 1~5（--author 建议填，UP 主是最强的推荐信号）
python score.py --bvid BV1xx4y1z7Ab --title "视频标题" --tags "科技、科普" --author "某UP主" --interest 4 --value 5
python score.py --list
python score.py --delete BV1xx4y1z7Ab     # 撤销某条打分
```

- 网页三档反馈的映射：**喜欢 → 兴趣5/价值4；无感 → 3/3（不改模型，但不再推荐）；踩雷 → 兴趣1/价值1**
- 同一 bvid 只保留一条记录（重复打分自动覆盖，不会重复计入训练）
- 打分原则：**只为"明显超出或低于预期"的视频打分**，没打分的视频不进训练样本——稀疏但干净，这正是显式反馈的优势
- 冷启动建议：翻历史记录/收藏夹回顾式打 30~50 条，再评价推荐质量

## 重新训练 / 更新模型

**没有"训练"这一步，也不需要手动重训。** 模型不持久化任何参数：

- 每次运行 `recommend.py`、或刷新 `serve.py` 网页，都会读取 `data/scores.csv` 里的**全部当前打分**，在几秒内重新计算双轴原型
- 所以"更新模型" = 追加打分 → 重新跑命令 / 刷新网页，立即生效
- 想验证模型质量：`python recommend.py --self-check 8`——留出 8 条打分用其余训练，对比预测兴趣与真实兴趣，输出命中率与平均误差
- **今日清单**：当天首次生成后固定不变（`data/daily/YYYY-MM-DD.json`），次日自动重算；命令行 `python recommend.py --daily` 查看，`--refresh` 强制重算
- **数据体检**：`python doctor.py`——自动修 GBK 编码、补 author 列、去重；加 `--enrich` 可补抓缺失的 UP 主/标题

## 网页服务参数

```powershell
python serve.py                  # 默认 http://127.0.0.1:8765/，自动打开浏览器
python serve.py --no-browser     # 静默启动：只起服务不弹浏览器（适合后台常驻/开机自启）
python serve.py --port 9000      # 指定端口
```

## 数据文件

| 文件 | 内容 |
| --- | --- |
| `data/scores.csv` | 你的双轴打分（bvid,title,tags,interest,value,ts），训练数据 |
| `data/candidates.csv` | 候选池（collector.py 自动生成，也可手动追加） |

> ⚠️ 本仓库为**公开**，`data/` 会随 git 推送，任何人可见你的打分与收藏夹标题。
> 介意的话删除敏感条目再提交，或把仓库改为私有。

## 跨机同步

- 换机器前的固定动作：**先 push 再离开，到达后先 pull 再打分**，避免两台机器分数互相覆盖
- 打分数据随 git 一起同步，无需网盘或手动拷贝

## 目录结构

```
my-bili-recs/
├── score.py                 # CLI 打分入口（--author / --delete）
├── collector.py             # B站分区排行榜候选收集（无需登录，含 UP 主，带风控退避重试）
├── recommend.py             # 双轴推荐引擎（停用词 / UP 主特征 / 探索位 / 每日清单 / 为什么推荐）
├── serve.py                 # 每日清单网页 + 三档反馈 + JSON 接口
├── storage.py               # 数据 schema 唯一定义处（scores / candidates 读写）
├── doctor.py                # 数据体检：修编码 / 补列 / 去重 / 补抓 UP 主
├── bili_meta.py             # B站公开接口抓元数据（标题 / UP主 / 标签）
├── requirements.txt
├── examples/                # 示例数据（供参考格式）
└── data/                    # 分数、候选、每日清单（随 git 同步）
```

## 常见问题

- **中文乱码 / 读不到数据**：不要用 Excel 编辑 `data/*.csv`（Excel 保存为 GBK，脚本读不了）。
  请用 VS Code 等 UTF-8 编辑器，或只用 `score.py` / 网页按钮打分
- **pip 装不上**：见上方"安装"节的 `NO_PROXY` 说明
- **候选拉取失败**：collector.py 用无需登录的公开排行榜接口，失败稍等重试；
  订阅 UP 主新投稿需要登录 cookie（M3/M4 规划中）
- **推荐分数都挤在 3.8~4.0 附近**：样本少时区分度有限，多打几轮"满意/踩雷"会逐渐拉开
