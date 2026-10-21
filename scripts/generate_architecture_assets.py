from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "images"
FONT_REGULAR = Path(r"C:\Windows\Fonts\msyh.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")

COLORS = {
    "background": "#f4f7fb",
    "surface": "#ffffff",
    "border": "#d7e0ea",
    "text": "#172033",
    "muted": "#64748b",
    "blue": "#2563eb",
    "blue_soft": "#eaf1ff",
    "green": "#0f9f6e",
    "green_soft": "#e9f8f2",
    "amber": "#c27803",
    "amber_soft": "#fff6df",
    "red": "#dc3e42",
    "red_soft": "#fdeced",
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size)


def rounded_box(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    title: str,
    body: str = "",
    fill: str = COLORS["surface"],
    border: str = COLORS["border"],
    title_color: str = COLORS["text"],
    title_size: int = 28,
    body_size: int = 20,
) -> None:
    draw.rounded_rectangle(xy, radius=18, fill=fill, outline=border, width=2)
    left, top, right, _ = xy
    draw.text((left + 24, top + 18), title, font=font(title_size, True), fill=title_color)
    if body:
        body_font = font(body_size)
        y = top + 62
        max_width = right - left - 48
        for paragraph in body.split("\n"):
            line = ""
            for char in paragraph:
                candidate = line + char
                if draw.textlength(candidate, font=body_font) > max_width and line:
                    draw.text((left + 24, y), line, font=body_font, fill=COLORS["muted"])
                    y += 30
                    line = char
                else:
                    line = candidate
            if line:
                draw.text((left + 24, y), line, font=body_font, fill=COLORS["muted"])
                y += 30


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str) -> None:
    draw.line((start, end), fill=color, width=3)
    x1, y1 = start
    x2, y2 = end
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        points = [(x2, y2), (x2 - 12 * direction, y2 - 7), (x2 - 12 * direction, y2 + 7)]
    else:
        direction = 1 if y2 > y1 else -1
        points = [(x2, y2), (x2 - 7, y2 - 12 * direction), (x2 + 7, y2 - 12 * direction)]
    draw.polygon(points, fill=color)


def make_architecture() -> None:
    image = Image.new("RGB", (1600, 1120), COLORS["background"])
    draw = ImageDraw.Draw(image)
    draw.text((70, 42), "系统架构与模块边界", font=font(42, True), fill=COLORS["text"])
    draw.text((72, 98), "单端口部署：页面、REST API、WebSocket、编排与本地数据层", font=font(22), fill=COLORS["muted"])

    rounded_box(
        draw,
        (60, 150, 1540, 285),
        "浏览器端",
        "提交工单  |  工单看板  |  进度查询  |  Agent 状态  |  实时日志\n"
        "静态资源：index.html + api.js + tailwind.css + CopilotKit widget",
        fill=COLORS["blue_soft"],
        border="#bfd2ff",
        title_color=COLORS["blue"],
    )

    rounded_box(
        draw,
        (60, 330, 1540, 485),
        "FastAPI 服务层",
        "JWT 鉴权  |  限流  |  Trace ID 请求日志  |  REST 路由  |  WebSocket 路由  |  静态文件服务\n"
        "统一校验输入、返回 404/409/422，并将工单状态变化推送到前端",
        fill=COLORS["surface"],
    )

    rounded_box(
        draw,
        (60, 530, 720, 700),
        "编排层",
        "Orchestrator\n主意图识别、多意图拆分、子工单生成、结果聚合",
        fill=COLORS["green_soft"],
        border="#bfe9d9",
        title_color=COLORS["green"],
    )
    rounded_box(
        draw,
        (770, 530, 1540, 700),
        "工单分析工作流",
        "LangGraph\n事实提取 -> 完整性检查 -> SOP/历史检索 -> 草稿与追问\n"
        "CopilotKit 工具只回填表单，不自动提交",
        fill=COLORS["amber_soft"],
        border="#f0d69a",
        title_color=COLORS["amber"],
    )

    agent_y = 750
    agent_width = 270
    gap = 25
    names = [
        ("IT Agent", "账号 / 硬件 / 网络 / 软件"),
        ("HR Agent", "假期 / 考勤 / 证明 / 政策"),
        ("采购 Agent", "用品 / 供应商 / 审批"),
        ("财务 Agent", "报销 / 预算 / 发票"),
        ("通用 Agent", "低置信度 / 人工兜底"),
    ]
    for index, (name, body) in enumerate(names):
        left = 60 + index * (agent_width + gap)
        rounded_box(
            draw,
            (left, agent_y, left + agent_width, 895),
            name,
            body,
            fill=COLORS["surface"],
            title_size=24,
            body_size=18,
        )

    rounded_box(
        draw,
        (60, 925, 570, 1050),
        "SQLite",
        "tickets / sub_tickets / snapshots",
        fill=COLORS["surface"],
        title_size=23,
        body_size=17,
    )
    rounded_box(
        draw,
        (600, 925, 1080, 1050),
        "知识检索",
        "knowledge/*.md + 历史工单 + BM25",
        fill=COLORS["surface"],
        title_size=23,
        body_size=17,
    )
    rounded_box(
        draw,
        (1110, 925, 1540, 1050),
        "技能目录",
        "15 个 Superpowers + 本地 to-tickets",
        fill=COLORS["surface"],
        title_size=23,
        body_size=17,
    )

    arrow(draw, (800, 285), (800, 330), COLORS["blue"])
    arrow(draw, (390, 485), (390, 530), COLORS["green"])
    arrow(draw, (1150, 485), (1150, 530), COLORS["amber"])
    arrow(draw, (390, 700), (390, 750), COLORS["green"])
    arrow(draw, (1150, 700), (1150, 750), COLORS["amber"])
    arrow(draw, (800, 895), (800, 925), COLORS["muted"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    image.save(OUT_DIR / "architecture.png", quality=95)


def make_workflow() -> None:
    image = Image.new("RGB", (1600, 1060), COLORS["background"])
    draw = ImageDraw.Draw(image)
    draw.text((70, 42), "工单处理流程", font=font(42, True), fill=COLORS["text"])
    draw.text((72, 98), "从自然语言输入到子任务完成、人工兜底与页面回显", font=font(22), fill=COLORS["muted"])

    steps = [
        ("1  输入", "用户填写表单，或由页面助手生成可编辑草稿", COLORS["blue_soft"], COLORS["blue"]),
        ("2  校验", "过滤空内容、纯符号和无意义重复字符", COLORS["surface"], COLORS["text"]),
        ("3  分类", "LLM 主分类；无 Key 或网络失败时降级为关键词规则", COLORS["amber_soft"], COLORS["amber"]),
        ("4  拆分", "识别 IT / HR / 采购 / 财务等多个独立意图", COLORS["surface"], COLORS["text"]),
        ("5  分派", "每个子工单进入对应 Agent 的独立后台线程", COLORS["green_soft"], COLORS["green"]),
    ]
    positions = [
        (70, 150, 550, 285),
        (585, 150, 1065, 285),
        (1100, 150, 1530, 285),
        (70, 345, 550, 480),
        (585, 345, 1065, 480),
    ]
    for (title, body, fill, title_color), xy in zip(steps, positions, strict=True):
        rounded_box(draw, xy, title, body, fill=fill, title_color=title_color, title_size=26, body_size=19)

    rounded_box(
        draw,
        (1100, 345, 1530, 480),
        "6  处理结果",
        "resolved：完成\nwaiting_info：等待补充\nfailed：转人工升级",
        fill=COLORS["surface"],
        title_size=26,
        body_size=19,
    )
    rounded_box(
        draw,
        (585, 545, 1065, 700),
        "7  waiting_info 闭环",
        "用户只补充缺失字段；同一子工单重新进入处理队列\n"
        "父工单保持 processing，直到全部子任务结束",
        fill=COLORS["amber_soft"],
        border="#f0d69a",
        title_color=COLORS["amber"],
    )
    rounded_box(
        draw,
        (70, 545, 550, 700),
        "8  SLA 监控",
        "后台 watchdog 每 5 秒扫描未结束子工单\n"
        "按部门阈值升级；等待补充单独计算宽限期",
        fill=COLORS["red_soft"],
        border="#f4c5c7",
        title_color=COLORS["red"],
    )
    rounded_box(
        draw,
        (1100, 545, 1530, 700),
        "9  聚合与回显",
        "汇总子任务结果、待补充问题、升级项和参考 SOP\n"
        "WebSocket 每秒比较状态并推送变化",
        fill=COLORS["green_soft"],
        border="#bfe9d9",
        title_color=COLORS["green"],
    )
    rounded_box(
        draw,
        (360, 790, 1240, 960),
        "人工确认边界",
        "页面助手只调用 fillTicketForm 回填可见表单；不会创建、修改或提交工单。\n"
        "最终提交、编辑和删除均由用户操作触发，后端再次校验工单是否存在及输入是否有效。",
        fill=COLORS["blue_soft"],
        border="#bfd2ff",
        title_color=COLORS["blue"],
        title_size=28,
        body_size=21,
    )

    arrow(draw, (550, 217), (585, 217), COLORS["muted"])
    arrow(draw, (1065, 217), (1100, 217), COLORS["muted"])
    arrow(draw, (1315, 285), (1315, 345), COLORS["muted"])
    arrow(draw, (1100, 412), (1065, 412), COLORS["muted"])
    arrow(draw, (585, 412), (550, 412), COLORS["muted"])
    arrow(draw, (310, 480), (310, 545), COLORS["red"])
    arrow(draw, (825, 480), (825, 545), COLORS["amber"])
    arrow(draw, (1315, 480), (1315, 545), COLORS["green"])
    arrow(draw, (825, 700), (825, 790), COLORS["blue"])

    image.save(OUT_DIR / "workflow.png", quality=95)


if __name__ == "__main__":
    make_architecture()
    make_workflow()
    print("Generated docs/images/architecture.png and docs/images/workflow.png")
