#!/usr/bin/env python3
"""BOSS Feature Pipeline 启动脚本 - 编排 Deploy→PRD→Dev→Test→Accept→HumanCheckpoint × 6 features"""
import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
WORKFLOW_CONFIG = PROJECT_DIR / ".claude" / "workflows" / "boss-feature-pipeline.json"

def load_config() -> dict:
    with open(WORKFLOW_CONFIG) as f:
        return json.load(f)

def main():
    config = load_config()
    features = config["features"]
    meta = config["meta"]

    print("=" * 70)
    print("  BOSS Feature Pipeline - 自动化开发工作流")
    print("=" * 70)
    print(f"  PRD: {meta['prd_path']}")
    print(f"  Target: {meta['target_url']}")
    print(f"  功能点数: {len(features)}")
    print(f"  模式: 迭代开发 + 人工验收断点")
    print("=" * 70)

    print("""
工作流步骤 (在 Claude Code 中执行):

阶段 0: 部署
  python3 scripts/deploy_agent.py → Docker部署+健康检查

阶段 1: PRD 分析
  Agent prd_reader: 阅读 docs/PRD.md → 提取6个功能点验收标准 → SendMessage developer

阶段 2-7: 功能点循环 (F1-F6)
  每个功能点:
  ├── developer: TDD实现 → SendMessage tester
  ├── tester (CUA): Playwright MCP视觉测试 → SendMessage acceptor
  └── acceptor: 比对验收标准
      ├── PASS → 人工确认断点 → 下一功能点
      └── FAIL → SendMessage developer (修复)

人工确认命令:
  /approve F{id}  → 通过，进入下一功能点
  /reject F{id}   → 不通过，回到开发修复
""")

    print("\n功能点清单:")
    for f in features:
        print(f"  {f['id']}: {f['name']} [{f['endpoint']}]")

    print("\nAgent 清单:")
    for sid, stage in config["stages"].items():
        print(f"  {sid}: {stage['name']} ({stage['agent_type']})")

    print("\n启动 Agent pipeline:")
    for sid, stage in config["stages"].items():
        print(f"  Agent(name='{stage['name']}', agent_type='{stage['agent_type']}', run_in_background=True)")
    print(f"\n  SendMessage(to='deployer', message='开始部署 {meta['project_name']}')\n")

if __name__ == "__main__":
    main()
