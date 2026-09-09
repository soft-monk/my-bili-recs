# 个人推荐层（B站）—— my-bili-recs

显式双轴打分（兴趣 / 价值）养出来的、只属于你自己的 B站视频推荐引擎。

- 设计文档：[docs/视频推荐想法整理.md](docs/视频推荐想法整理.md)（想法来源与调研）
- 实现方案：[docs/B站个人推荐层实现方案.md](docs/B站个人推荐层实现方案.md)（架构 / 算法 / 里程碑）

## 核心思想

平台算法优化的是"平台要的时长"，不是"你想要的视频"。本项目把目标函数夺回来：
你给看过的视频打 **兴趣分**（我喜不喜欢）和 **价值分**（值不值得看），本地模型学出双轴原型，
对候选视频先过滤垃圾、再按口味排序。

## 当前进度：M2（排行榜候选池）

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| M1 | CLI 打分 + TF-IDF 双轴推荐闭环 | ✅ 完成 |
| M2 | B站候选池：分区排行榜自动收集（订阅源待登录 cookie） | ✅ 当前 |
| M3 | 油猴脚本在 B站页面一键双轴打分 | 计划中 |
| M4 | 每日精选网页（serve.py）✅ / 页内重排 / 推送 / 探索位 / 评估统计 | 进行中 |

## M1 快速上手

```powershell
pip install -r requirements.txt

# 第 0 步（只做一次）：回顾式打分——翻历史记录/收藏夹，给看过的视频打分
python score.py --bvid BV1xx4y1z7Ab --title "视频标题" --tags "科技,科普" --interest 4 --value 5
python score.py --list

# 第 1 步：准备候选——自动拉分区排行榜（M2，无需登录）
python collector.py --top 30

# 第 2 步：跑推荐
python recommend.py --top 10

# 第 3 步：打开每日精选网页（自动开浏览器，含满意/踩雷反馈按钮）
python serve.py

# 自检（可选）：留出 8 条打分，验证模型能否复现你的口味
python recommend.py --self-check 8
```

打分原则：**只为"明显超出或低于预期"的视频打分**。没打分的视频不进训练样本——
稀疏但干净，这正是显式反馈的优势。建议攒到 30~50 条后再评价推荐质量。

## 目录结构

```
my-bili-recs/
├── score.py                 # CLI 打分入口
├── collector.py             # M2：B站分区排行榜候选收集（无需登录）
├── recommend.py             # 双轴推荐引擎（TF-IDF + 原型向量）
├── serve.py                 # M4：每日精选网页 + 满意/踩雷反馈回写
├── requirements.txt
├── examples/                # 示例数据（供参考格式）
└── data/                    # 你的分数与候选（随私有仓库同步）
```

## 数据同步（跨机）

- 仓库为私有：`data/` 打分数据随 git 一起同步，任何机器 `git clone` + `git pull` 即可继续打分
- 换机器前的固定动作：**先 push 再离开，到达后先 pull 再打分**，避免两台机器分数互相覆盖
- 数据格式：`data/scores.csv`（打分）+ `data/candidates.csv`（候选），均为 UTF-8 CSV
