"""AI简历分析模块 — 使用DeepSeek分析简历与岗位匹配度，标记可约面候选人"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from app.config import settings
from app.database import Database
from app.logging_config import logger

# 匹配度阈值：high 或 medium 都标记为 recommend_interview
_MATCH_THRESHOLD = {"high", "medium"}


def _load_job_description() -> str:
    """读取当前注入的岗位描述"""
    job_info_dir = Path(__file__).parent.parent / "job_info"
    selected_file = job_info_dir / ".selected"
    if selected_file.exists():
        selected = selected_file.read_text("utf-8").strip()
        job_file = job_info_dir / f"{selected}.txt"
        if job_file.exists():
            return job_file.read_text("utf-8").strip()
    fallback = job_info_dir / "company_profile.txt"
    if fallback.exists():
        return fallback.read_text("utf-8").strip()
    return ""


def _extract_pdf_text(pdf_path: str) -> str:
    """提取PDF文本内容"""
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        texts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                texts.append(t)
        return "\n".join(texts)
    except Exception as e:
        logger.warning(f"[Analyze] PDF提取失败: {pdf_path} — {e}")
        return ""


async def _call_deepseek_analyze(resume_text: str, job_desc: str) -> Dict:
    """调用DeepSeek API分析简历与岗位匹配度"""
    prompt = f"""你是一位专业招聘官。请分析以下候选人与岗位的匹配度。

岗位描述：
{job_desc[:3000]}

候选人简历：
{resume_text[:4000]}

请输出JSON格式（不要其他内容）：
{{"fit": "high"|"medium"|"low", "reason": "一句话简要理由"}}"""

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{settings.DEEPSEEK_BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                     "Content-Type": "application/json"},
            json={
                "model": settings.DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 200,
            },
        )
    if response.status_code != 200:
        raise RuntimeError(f"API调用失败: HTTP {response.status_code}")
    data = response.json()
    content = data["choices"][0]["message"]["content"].strip()
    # 提取JSON（可能被```包裹）
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    return json.loads(content)


async def _analyze_resumes_impl(limit: int = 20, user_id: int = None) -> Dict:
    """AI简历分析主逻辑"""
    job_desc = _load_job_description()
    if not job_desc:
        return {"status": "error", "message": "未找到岗位描述文件，请先在岗位模板中设置"}

    db = Database()
    db.connect()
    db.init_tables()

    candidates = db.get_candidates_with_resumes(user_id=user_id)
    analyzed = 0
    matched = 0
    results = []

    for c in candidates:
        if analyzed >= limit:
            break
        boss_id = c["boss_id"]
        name = c.get("candidate_name", "")
        resume_path = c.get("resume_path", "")
        existing_status = c.get("interview_status") or ""

        # 跳过已分析过的
        if existing_status in ("recommend_interview", "not_recommended"):
            continue

        if not resume_path or not Path(resume_path).exists():
            logger.info(f"[Analyze] {name}: 简历文件不存在, 跳过")
            continue

        logger.info(f"[Analyze] 分析 ({analyzed+1}/{limit}): {name}")

        resume_text = _extract_pdf_text(resume_path)
        if not resume_text or len(resume_text) < 50:
            # 用候选人结构化数据回退
            structured = f"候选人: {name}\n"
            if c.get("school"):
                structured += f"学校: {c['school']}\n"
            if c.get("degree"):
                structured += f"学历: {c['degree']}\n"
            if c.get("years"):
                structured += f"工作年限: {c['years']}年\n"
            if c.get("skills"):
                structured += f"技能: {c['skills']}\n"
            if c.get("current_title"):
                structured += f"当前职位: {c['current_title']}\n"
            if c.get("expected_role"):
                structured += f"期望职位: {c['expected_role']}\n"
            resume_text = structured
            logger.info(f"[Analyze] {name}: PDF文本不足，改用结构化数据")

        try:
            result = await _call_deepseek_analyze(resume_text, job_desc)
            fit = result.get("fit", "low")
            reason = result.get("reason", "")
            if fit in _MATCH_THRESHOLD:
                db.set_candidate_interview_status(boss_id, "recommend_interview", user_id=user_id)
                matched += 1
                logger.info(f"[Analyze] {name}: ✅ {fit} — {reason}")
            else:
                db.set_candidate_interview_status(boss_id, "not_recommended", user_id=user_id)
                logger.info(f"[Analyze] {name}: ❌ {fit} — {reason}")
            results.append({"name": name, "fit": fit, "reason": reason, "school": c.get("school", ""), "years": c.get("years", ""), "degree": c.get("degree", "")})
        except Exception as e:
            logger.error(f"[Analyze] {name}: 分析失败 — {e}")
            db.set_candidate_interview_status(boss_id, "not_recommended", user_id=user_id)
            results.append({"name": name, "fit": "error", "reason": str(e), "school": c.get("school", ""), "years": c.get("years", ""), "degree": c.get("degree", "")})

        analyzed += 1

    db.close()

    # 写分析报告到简历目录
    report_dir = Path(__file__).parent.parent / "data" / "resumes"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"analyze_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    lines = [f"# AI简历分析报告", f"", f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
             f"**分析人数**: {analyzed} | **匹配**: {matched} | **不匹配**: {analyzed - matched}", f""]
    for r in results:
        emoji = {"high": "🟢", "medium": "🟡", "low": "🔴", "error": "⚠️"}.get(r["fit"], "❓")
        lines.append(f"- {emoji} **{r['name']}** ({r.get('school','')} | {r.get('years','')}年 | {r.get('degree','')}) — {r['reason']}")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"[Analyze] 报告已保存: {report_path}")

    return {
        "status": "completed",
        "analyzed": analyzed,
        "matched": matched,
        "not_matched": analyzed - matched,
        "message": f"分析完成: {analyzed}人, 匹配{matched}人",
    }
