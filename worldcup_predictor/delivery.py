from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .calibration import build_model_validation_status
from .live_readiness import build_live_readiness_status
from .report import build_excel_report, build_pdf_report
from .storage import storage_health
from .web_server import run_sample_prediction

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_delivery_audit(
    *,
    run_tests: bool = False,
    run_frontend_check: bool = True,
    write_output: bool = False,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    health = storage_health()
    validation = build_model_validation_status()
    readiness = build_live_readiness_status(
        model_validation=validation,
        storage=health,
    )

    _add_check(
        checks,
        "本地数据库可用",
        bool(health.get("db_path")) and Path(str(health.get("db_path"))).exists(),
        f"数据库：{health.get('db_path') or '-'}；预测 {health.get('prediction_runs', 0)} 条；盘口报价 {health.get('market_quotes', 0)} 条。",
    )
    _add_check(
        checks,
        "结构化盘口建库",
        int(health.get("market_quotes") or 0) >= 1,
        f"market_quotes={int(health.get('market_quotes') or 0)}。",
    )
    _add_check(
        checks,
        "正式 EV 关闭",
        not bool(validation.get("formalEvEnabled")),
        f"{validation.get('formalEvLabel') or '-'}；pfinal={validation.get('pfinalStatus') or '-'}。",
    )
    _add_check(
        checks,
        "真实资金闸门",
        not bool(readiness.get("canUseRealMoney")),
        f"{readiness.get('statusLabel') or '-'}；{readiness.get('realMoneyLabel') or '-'}。",
    )
    _add_check(
        checks,
        "校准样本透明披露",
        True,
        (
            f"合格赛前已结算样本 {validation.get('eligibleSamples', 0)} / "
            f"{(validation.get('policy') or {}).get('min_eligible_samples', 100)}；"
            f"状态 {validation.get('statusLabel') or validation.get('status') or '-'}。"
        ),
        blocking=False,
    )

    sample_payload = run_sample_prediction(match_id="MEX-USA")
    _add_check(
        checks,
        "样例预测链路",
        bool((sample_payload.get("probabilities") or {}).get("pbase"))
        and bool(sample_payload.get("recommendations")),
        "本地样例预测可生成 pbase、展示概率、模拟舱和报告 payload。",
    )
    excel = build_excel_report(sample_payload)
    pdf = build_pdf_report(sample_payload)
    _add_check(
        checks,
        "中文 Excel 报告",
        excel.startswith(b"PK") and len(excel) > 1000,
        f"已生成 {len(excel)} bytes xlsx。",
    )
    _add_check(
        checks,
        "中文 PDF 报告",
        pdf.startswith(b"%PDF") and len(pdf) > 1000,
        f"已生成 {len(pdf)} bytes pdf。",
    )

    if run_frontend_check:
        if shutil.which("node"):
            _add_subprocess_check(
                checks,
                "前端脚本语法",
                [shutil.which("node") or "node", "-c", "web/app.js"],
            )
        else:
            _add_check(
                checks,
                "前端脚本语法",
                True,
                "本机未发现 node，跳过 web/app.js 语法检查。",
                blocking=False,
            )

    if run_tests:
        _add_subprocess_check(checks, "Python 编译检查", [sys.executable, "-m", "compileall", "worldcup_predictor"])
        _add_subprocess_check(
            checks,
            "自动化测试",
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            timeout=120,
        )

    blocking_passed = all(item["passed"] for item in checks if item["blocking"])
    audit = {
        "generatedAt": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S 北京时间"),
        "deliveryStatus": "DELIVERABLE_RESEARCH_SYSTEM" if blocking_passed else "DELIVERY_BLOCKED",
        "deliveryStatusLabel": "可交付研究验证版" if blocking_passed else "交付阻塞",
        "liveStatus": readiness.get("status"),
        "liveStatusLabel": readiness.get("statusLabel"),
        "canUseRealMoney": bool(readiness.get("canUseRealMoney")),
        "formalEvEnabled": bool(validation.get("formalEvEnabled")),
        "modelValidation": {
            "status": validation.get("status"),
            "statusLabel": validation.get("statusLabel"),
            "eligibleSamples": validation.get("eligibleSamples"),
            "distinctFixtures": validation.get("distinctFixtures"),
            "pfinalStatus": validation.get("pfinalStatus"),
            "formalEvEnabled": validation.get("formalEvEnabled"),
        },
        "storage": health,
        "checks": checks,
        "blockingFailures": [item for item in checks if item["blocking"] and not item["passed"]],
        "boundary": [
            "本交付状态只证明程序链路、报告、存储和风险闸门可运行。",
            "当前正式 EV 与真实资金仍关闭；收益能力必须通过后续赛前样本、校准、纸上账本和复盘验证。",
            "如果模型没有稳定优势，合格系统的正确输出就是观望，而不是强行给信号。",
        ],
    }
    if write_output:
        audit["outputPath"] = str(_write_audit(audit))
    return audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run final delivery audit for World Cup predictor.")
    parser.add_argument("--full", action="store_true", help="Run compile check and unit tests.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--no-write", action="store_true", help="Do not write audit JSON to outputs/.")
    args = parser.parse_args(argv)

    audit = build_delivery_audit(run_tests=args.full, write_output=not args.no_write)
    if args.json:
        print(json.dumps(audit, ensure_ascii=False, indent=2))
    else:
        print(format_delivery_audit(audit))
    return 0 if audit["deliveryStatus"] == "DELIVERABLE_RESEARCH_SYSTEM" else 1


def format_delivery_audit(audit: dict[str, Any]) -> str:
    lines = [
        f"世界杯预测交付验收：{audit.get('deliveryStatusLabel')}",
        f"生成时间：{audit.get('generatedAt')}",
        f"实盘状态：{audit.get('liveStatusLabel')}；真实资金：{'可用' if audit.get('canUseRealMoney') else '禁止'}",
        f"正式 EV：{'已开放' if audit.get('formalEvEnabled') else '关闭'}",
        "",
        "验收项：",
    ]
    for item in audit.get("checks") or []:
        icon = "OK" if item.get("passed") else "FAIL"
        scope = "阻塞" if item.get("blocking") else "提示"
        lines.append(f"- [{icon}] {item.get('label')}（{scope}）：{item.get('detail')}")
    failures = audit.get("blockingFailures") or []
    if failures:
        lines.extend(["", "阻塞项："])
        lines.extend(f"- {item.get('label')}: {item.get('detail')}" for item in failures)
    if audit.get("outputPath"):
        lines.extend(["", f"审计文件：{audit['outputPath']}"])
    lines.extend(["", "边界："])
    lines.extend(f"- {item}" for item in audit.get("boundary") or [])
    return "\n".join(lines)


def _add_check(
    checks: list[dict[str, Any]],
    label: str,
    passed: bool,
    detail: str,
    *,
    blocking: bool = True,
) -> None:
    checks.append(
        {
            "label": label,
            "passed": bool(passed),
            "detail": detail,
            "blocking": bool(blocking),
        }
    )


def _add_subprocess_check(
    checks: list[dict[str, Any]],
    label: str,
    command: list[str],
    *,
    timeout: int = 60,
) -> None:
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - delivery audit should report failures, not crash.
        _add_check(checks, label, False, str(exc))
        return
    output = (completed.stdout + "\n" + completed.stderr).strip()
    tail = "\n".join(output.splitlines()[-6:]) if output else "无输出"
    _add_check(checks, label, completed.returncode == 0, tail)


def _write_audit(audit: dict[str, Any]) -> Path:
    output_dir = PROJECT_ROOT / "outputs" / "delivery_audit"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"delivery_audit_{stamp}.json"
    path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
