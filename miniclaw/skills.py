#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: skills.py
# @Description: 技能加载器和触发器匹配器
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/19 14:19
# @Version: 1.0

"""Skill loader and trigger matcher.

Skills in OpenClaw are YAML+Markdown files that define:
- Triggers (keywords, regex patterns)
- Tool declarations (what tools the skill needs)
- System prompt additions (context for the LLM)

MiniClaw uses Markdown with YAML front-matter for skill definitions.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)


@dataclass
class Trigger:
    """触发器数据类，描述一个技能的激活条件。

    支持三种触发类型：
    - keyword：关键词匹配（大小写不敏感的子串匹配）
    - regex：正则表达式匹配（大小写不敏感）
    - always：无条件触发，每次用户输入都会激活对应技能
    """

    # 触发器类型，取值为 "keyword" | "regex" | "always"
    type: str
    # 匹配模式：keyword 类型为关键词字符串，regex 类型为正则表达式，always 类型可为空
    pattern: str = ""

    def matches(self, text: str) -> bool:
        """判断给定文本是否满足该触发器的激活条件。

        :param text: 用户输入的原始文本
        :return: 若触发条件满足则返回 True，否则返回 False
        """
        # always 类型无条件返回 True，始终激活
        if self.type == "always":
            return True
        # keyword 类型：忽略大小写，判断 pattern 是否为 text 的子串
        if self.type == "keyword":
            return self.pattern.lower() in text.lower()
        # regex 类型：使用正则表达式进行大小写不敏感的全文搜索
        if self.type == "regex":
            return bool(re.search(self.pattern, text, re.IGNORECASE))
        # 未知触发器类型，默认不匹配
        return False


@dataclass
class Skill:
    """技能数据类，表示从 Markdown 文件解析出的一个完整技能定义。

    每个技能包含触发条件、所需工具列表以及注入 LLM 系统提示的额外上下文。
    """

    # 技能的唯一名称，默认取自文件名（不含扩展名）
    name: str
    # 技能的简短描述，用于构建技能索引展示给 LLM
    description: str
    # 触发器列表，任意一个触发器匹配即视为该技能被激活
    triggers: list[Trigger]
    # 该技能所需的工具名称列表，供 Agent 按需加载对应工具
    tools: list[str]
    # 技能激活时追加到系统提示中的 Markdown 正文内容
    prompt: str
    # 技能定义文件的原始路径，便于调试和日志追踪；可为 None
    source_path: Path | None = None

    def matches(self, text: str) -> bool:
        """判断给定文本是否能激活该技能（任意触发器匹配即可）。

        :param text: 用户输入的原始文本
        :return: 若至少一个触发器匹配则返回 True，否则返回 False
        """
        # 遍历所有触发器，只要有一个匹配就立即返回 True（短路求值）
        return any(t.matches(text) for t in self.triggers)


class SkillRegistry:
    """技能注册表，负责从 workspace/skills/ 目录加载并管理所有技能。

    职责：
    1. 扫描指定目录下的 .md 技能文件并解析为 Skill 对象
    2. 根据用户输入文本匹配已激活的技能列表
    3. 构建供 LLM 感知的技能索引摘要
    """

    def __init__(self):
        # 内部技能列表，按文件名字母序排列（由 load_from_directory 保证）
        self._skills: list[Skill] = []

    def load_from_directory(self, skills_dir: Path) -> int:
        """扫描指定目录，解析其中所有 .md 技能文件并注册到内部列表。

        :param skills_dir: 存放技能 Markdown 文件的目录路径
        :return: 成功加载的技能数量；若目录不存在则返回 0
        """
        # 目录不存在时直接返回，避免抛出异常
        if not skills_dir.exists():
            return 0

        count = 0
        # 按文件名字母序遍历，保证加载顺序的确定性
        for path in sorted(skills_dir.glob("*.md")):
            try:
                skill = self._parse_skill_file(path)
                self._skills.append(skill)
                count += 1
                logger.info(f"Loaded skill: {skill.name} ({len(skill.triggers)} triggers)")
            except Exception as e:
                # 单个文件解析失败不影响其他技能的加载，仅记录警告
                logger.warning(f"Failed to parse skill {path.name}: {e}")

        return count

    def match(self, text: str) -> list[Skill]:
        """根据用户输入文本，返回所有触发器匹配的技能列表。

        :param text: 用户输入的原始文本
        :return: 所有被激活的 Skill 对象列表；若无匹配则返回空列表
        """
        # 列表推导式过滤出所有 matches 返回 True 的技能
        return [s for s in self._skills if s.matches(text)]

    def build_index(self) -> str:
        """构建所有已加载技能的紧凑索引字符串，用于注入系统提示。

        该索引始终出现在系统提示中（每个技能约 100 tokens），
        使 LLM 能感知当前可用的技能能力，而无需承担每个技能完整正文的 token 开销。
        技能正文仅在触发器命中时由 Router 单独注入。

        :return: Markdown 格式的技能索引字符串；若无技能则返回空字符串
        """
        # 没有任何技能时返回空字符串，避免在系统提示中出现空标题
        if not self._skills:
            return ""

        lines = ["## Available Skills (loaded on demand)"]
        for s in self._skills:
            # 收集非 always 类型触发器的 pattern，拼接为可读的触发词列表
            triggers = ", ".join(
                t.pattern for t in s.triggers if t.type != "always"
            )
            # 若存在具体触发词，则在描述后追加触发词信息
            trigger_info = f" (triggers: {triggers})" if triggers else ""
            lines.append(f"- **{s.name}**: {s.description}{trigger_info}")

        return "\n".join(lines)

    def list_skills(self) -> list[dict[str, str]]:
        """返回所有已加载技能的名称和描述列表，供外部模块枚举展示。

        :return: 每个元素包含 'name' 和 'description' 键的字典列表
        """
        return [
            {"name": s.name, "description": s.description}
            for s in self._skills
        ]

    def get_skill(self, name: str) -> Skill | None:
        """按名称精确查找技能。

        :param name: 技能名称（区分大小写）
        :return: 匹配的 Skill 对象；若不存在则返回 None
        """
        for s in self._skills:
            if s.name == name:
                return s
        # 未找到时返回 None，由调用方决定如何处理
        return None

    def _parse_skill_file(self, path: Path) -> Skill:
        """解析单个技能 Markdown 文件，将其转换为 Skill 数据对象。

        文件格式为带 YAML front-matter 的 Markdown：
        - front-matter 中声明 name、description、triggers、tools 等元数据
        - Markdown 正文作为技能激活时追加到系统提示的上下文内容

        :param path: 技能 Markdown 文件的路径
        :return: 解析完成的 Skill 对象
        :raises Exception: 当文件格式不合法或必要字段缺失时抛出
        """
        # 使用 python-frontmatter 库同时解析 YAML 元数据和 Markdown 正文
        post = frontmatter.load(str(path))
        meta = post.metadata

        # 解析触发器列表，支持字符串（默认 keyword 类型）和字典两种写法
        triggers = []
        for t in meta.get("triggers", []):
            if isinstance(t, str):
                # 简写形式：直接写字符串，默认视为 keyword 类型触发器
                triggers.append(Trigger(type="keyword", pattern=t))
            elif isinstance(t, dict):
                # 完整形式：通过字典指定 type 和 pattern，type 默认为 keyword
                triggers.append(Trigger(
                    type=t.get("type", "keyword"),
                    pattern=t.get("pattern", ""),
                ))

        # 兼容 tools 字段写成单个字符串的情况，统一转为列表
        raw_tools = meta.get("tools", [])
        if isinstance(raw_tools, str):
            raw_tools = [raw_tools]

        return Skill(
            # 技能名称优先取 front-matter 中的 name，缺省时使用文件名（不含扩展名）
            name=meta.get("name", path.stem),
            description=meta.get("description", ""),
            triggers=triggers,
            # raw_tools 为 None 或空列表时统一返回空列表
            tools=raw_tools or [],
            # post.content 为去除 front-matter 后的 Markdown 正文
            prompt=post.content,
            source_path=path,
        )
