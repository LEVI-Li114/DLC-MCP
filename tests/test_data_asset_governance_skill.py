from pathlib import Path


def test_data_asset_governance_skill_contains_required_guardrails():
    path = Path(".claude/skills/data-asset-governance/SKILL.md")
    text = path.read_text(encoding="utf-8")

    assert "get_asset_governance_issue_inventory" in text
    assert "Do not invent issue facts or owners" in text
    assert "Do not treat absent data as healthy" in text
    assert "ListTablePartitions InvalidAction" in text
    assert "action/version unsupported" in text
    assert "real missing task/run coverage" in text
    assert "Every recommendation must cite issue evidence" in text
    assert "# 数据资产治理方案" in text
