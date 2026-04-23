import json
import os
import re
import shutil
import time
import tempfile
from datetime import datetime, timezone
from typing import Iterable

import requests
from loguru import logger


REQUEST_TIMEOUT = 30
REQUEST_RETRIES = 4
OUTPUT_DIR = "output"
SNAPSHOTS_DIR = "snapshots"
DEFAULT_HEADERS = {
    "User-Agent": "user-agents-updater/2.0"
}


class UserAgents:
    def __init__(self, output_dir: str = OUTPUT_DIR, snapshots_dir: str = SNAPSHOTS_DIR):
        self.output_dir = output_dir
        self.snapshots_dir = snapshots_dir
        self.current_user_agents: list[str] = []
        self.current_metadata: dict = {}
        self.user_agents: list[str] = []
        self.snapshot_name: str = ""

    @staticmethod
    def remove_duplicates(items: Iterable[str]) -> list[str]:
        """去重并保留首次出现的顺序。"""
        return list(dict.fromkeys(items))

    @staticmethod
    def version_tuple(version: str) -> tuple[int, ...]:
        match = re.search(r"\d+(?:\.\d+)*", version)
        if match is None:
            raise ValueError(f"无法解析版本号: {version}")
        return tuple(int(part) for part in match.group(0).split("."))

    @staticmethod
    def major_version(version: str) -> int:
        return UserAgents.version_tuple(version)[0]

    def request_json(self, url: str) -> dict | list:
        last_error = None
        for attempt in range(1, REQUEST_RETRIES + 1):
            try:
                logger.info(f"🌐 请求 JSON: {url} (attempt {attempt}/{REQUEST_RETRIES})")
                response = requests.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                if attempt == REQUEST_RETRIES:
                    break
                sleep_seconds = attempt * 2
                logger.warning(f"请求失败，将在 {sleep_seconds}s 后重试: {url} - {exc}")
                time.sleep(sleep_seconds)

        raise RuntimeError(f"请求数据源失败: {url}") from last_error

    def fetch_chrome_user_agents(self) -> tuple[list[str], dict]:
        platforms = {
            "mac": "Macintosh; Intel Mac OS X 10_15_7",
            "win": "Windows NT 10.0; Win64; x64",
            "linux": "X11; Linux x86_64",
        }
        user_agents = []
        metadata = {}
        for api_platform, ua_platform in platforms.items():
            data = self.request_json(
                f"https://versionhistory.googleapis.com/v1/chrome/platforms/{api_platform}/channels/stable/versions"
            )
            versions = data.get("versions", [])
            majors = sorted(
                {self.major_version(item["version"]) for item in versions if item.get("version")}
            )
            if len(majors) < 2:
                raise RuntimeError(f"Chrome {api_platform} 平台可用主版本不足 2 个")

            selected_majors = majors[-2:]
            metadata[api_platform] = {
                "source": "https://versionhistory.googleapis.com",
                "majors": selected_majors,
            }
            for major in selected_majors:
                user_agents.append(
                    "Mozilla/5.0 "
                    f"({ua_platform}) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    f"Chrome/{major}.0.0.0 Safari/537.36"
                )

        return user_agents, metadata

    def fetch_firefox_user_agents(self) -> tuple[list[str], dict]:
        data = self.request_json("https://product-details.mozilla.org/1.0/firefox_versions.json")
        release_version = data.get("LATEST_FIREFOX_VERSION")
        esr_version = data.get("FIREFOX_ESR")
        if not release_version or not esr_version:
            raise RuntimeError("Firefox 版本接口缺少 release 或 esr 数据")

        release_major = self.major_version(release_version)
        esr_major = self.major_version(esr_version)
        platforms = (
            "Macintosh; Intel Mac OS X 10.15",
            "Windows NT 10.0; Win64; x64",
            "X11; Linux x86_64",
            "X11; Ubuntu; Linux x86_64",
        )

        user_agents = []
        for ua_platform in platforms:
            for major in (esr_major, release_major):
                user_agents.append(
                    f"Mozilla/5.0 ({ua_platform}; rv:{major}.0) Gecko/20100101 Firefox/{major}.0"
                )

        metadata = {
            "source": "https://product-details.mozilla.org/1.0/firefox_versions.json",
            "release_version": release_version,
            "release_major": release_major,
            "esr_version": esr_version,
            "esr_major": esr_major,
        }
        return user_agents, metadata

    def fetch_edge_user_agents(self) -> tuple[list[str], dict]:
        data = self.request_json("https://edgeupdates.microsoft.com/api/products")
        stable_product = next(
            (item for item in data if str(item.get("Product", "")).lower() == "stable"),
            None,
        )
        if stable_product is None:
            raise RuntimeError("Edge Updates API 未返回 Stable 产品线")

        releases = stable_product.get("Releases", [])
        windows_releases = [item for item in releases if item.get("Platform") == "Windows"]
        if not windows_releases:
            raise RuntimeError("Edge Updates API 未返回 Windows 稳定版发布记录")

        preferred_releases = [
            item for item in windows_releases if str(item.get("Architecture", "")).lower() == "x64"
        ] or windows_releases
        latest_release = max(
            preferred_releases,
            key=lambda item: (
                item.get("PublishedTime", ""),
                self.version_tuple(item.get("ProductVersion", "0")),
            ),
        )
        version = latest_release.get("ProductVersion")
        if not version:
            raise RuntimeError("Edge 发布记录缺少 ProductVersion")

        major = self.major_version(version)
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36 Edg/{major}.0.0.0"
        )
        metadata = {
            "source": "https://edgeupdates.microsoft.com/api/products",
            "version": version,
            "major": major,
            "published_time": latest_release.get("PublishedTime"),
            "architecture": latest_release.get("Architecture"),
        }
        return [user_agent], metadata

    def fetch_safari_user_agents(self) -> tuple[list[str], dict]:
        sources = (
            (
                "https://developer.apple.com/tutorials/data/index/safari-release-notes",
                self.extract_safari_titles_from_index,
            ),
            (
                "https://developer.apple.com/tutorials/data/documentation/safari-release-notes.json",
                self.extract_safari_titles_from_references,
            ),
        )

        versions = []
        selected_source = None
        for url, extractor in sources:
            try:
                data = self.request_json(url)
                titles = extractor(data)
                versions = self.extract_stable_safari_versions(titles)
                if versions:
                    selected_source = url
                    break
            except Exception as exc:
                logger.warning(f"Safari 数据源读取失败: {url} - {exc}")

        if not versions or selected_source is None:
            raise RuntimeError("无法从 Apple 官方数据源获取 Safari 正式版版本号")

        version = max(versions, key=self.version_tuple)
        user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            f"Version/{version} Safari/605.1.15"
        )
        metadata = {
            "source": selected_source,
            "version": version,
        }
        return [user_agent], metadata

    @staticmethod
    def extract_safari_titles_from_index(data: dict) -> list[str]:
        children = data["interfaceLanguages"]["swift"][0]["children"]
        return [item["title"] for item in children if item.get("type") == "article"]

    @staticmethod
    def extract_safari_titles_from_references(data: dict) -> list[str]:
        references = data.get("references", {}).values()
        return [item["title"] for item in references if item.get("kind") == "article"]

    @staticmethod
    def extract_stable_safari_versions(titles: Iterable[str]) -> list[str]:
        versions = []
        for title in titles:
            if re.search(r"(?i)\bbeta\b", title):
                continue
            match = re.search(r"^Safari ([0-9]+(?:\.[0-9]+)*) Release Notes$", title)
            if match:
                versions.append(match.group(1))
        return versions

    def generate_current_user_agents(self):
        logger.info("🚀 开始基于官方数据源生成最新 User-Agent")
        chrome_uas, chrome_meta = self.fetch_chrome_user_agents()
        firefox_uas, firefox_meta = self.fetch_firefox_user_agents()
        safari_uas, safari_meta = self.fetch_safari_user_agents()
        edge_uas, edge_meta = self.fetch_edge_user_agents()

        current_user_agents = chrome_uas + firefox_uas + safari_uas + edge_uas
        current_user_agents = self.remove_duplicates(current_user_agents)
        self.validate_current_user_agents(current_user_agents)

        generated_at = datetime.now(timezone.utc)
        self.current_user_agents = current_user_agents
        self.snapshot_name = generated_at.strftime("%Y-%m-%dT%H-%M-%SZ.json")
        self.current_metadata = {
            "generated_at": generated_at.isoformat(),
            "sources": {
                "chrome": chrome_meta,
                "firefox": firefox_meta,
                "safari": safari_meta,
                "edge": edge_meta,
            },
        }
        logger.info(f"🎉 当前版本共生成 {len(self.current_user_agents)} 条 User-Agent")

    @staticmethod
    def validate_current_user_agents(user_agents: list[str]):
        if len(user_agents) != 16:
            raise RuntimeError(f"当前 User-Agent 数量异常，期望 16 条，实际 {len(user_agents)} 条")

        chrome_count = sum(" Chrome/" in ua and " Edg/" not in ua for ua in user_agents)
        firefox_count = sum(" Firefox/" in ua for ua in user_agents)
        safari_count = sum(" Version/" in ua and " Safari/" in ua and " Chrome/" not in ua for ua in user_agents)
        edge_count = sum(" Edg/" in ua for ua in user_agents)

        if chrome_count != 6:
            raise RuntimeError(f"Chrome 数量异常，期望 6 条，实际 {chrome_count} 条")
        if firefox_count != 8:
            raise RuntimeError(f"Firefox 数量异常，期望 8 条，实际 {firefox_count} 条")
        if safari_count != 1:
            raise RuntimeError(f"Safari 数量异常，期望 1 条，实际 {safari_count} 条")
        if edge_count != 1:
            raise RuntimeError(f"Edge 数量异常，期望 1 条，实际 {edge_count} 条")

    def build_snapshot_payload(self) -> dict:
        return {
            "generated_at": self.current_metadata["generated_at"],
            "sources": self.current_metadata["sources"],
            "user_agents": self.current_user_agents,
        }

    def load_history_user_agents(self) -> list[str]:
        all_user_agents = list(self.current_user_agents)
        if not os.path.isdir(self.snapshots_dir):
            return self.remove_duplicates(all_user_agents)

        snapshot_files = sorted(
            file_name for file_name in os.listdir(self.snapshots_dir) if file_name.endswith(".json")
        )
        for file_name in reversed(snapshot_files):
            snapshot_path = os.path.join(self.snapshots_dir, file_name)
            with open(snapshot_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict):
                user_agents = data.get("user_agents", [])
            elif isinstance(data, list):
                user_agents = data
            else:
                raise RuntimeError(f"未知快照格式: {snapshot_path}")
            all_user_agents.extend(user_agents)

        return self.remove_duplicates(all_user_agents)

    def classify_user_agents(self) -> dict:
        classified = {
            "Windows": {"chrome": [], "firefox": [], "edge": []},
            "Mac": {"chrome": [], "firefox": [], "safari": []},
            "Linux": {"chrome": [], "firefox": []},
        }

        logger.info("🔄 开始分类 User-Agent")
        for ua in self.user_agents:
            if "Windows" in ua:
                if " Edg/" in ua:
                    classified["Windows"]["edge"].append(ua)
                elif " Firefox/" in ua:
                    classified["Windows"]["firefox"].append(ua)
                elif " Chrome/" in ua:
                    classified["Windows"]["chrome"].append(ua)
            elif "Macintosh" in ua:
                if " Firefox/" in ua:
                    classified["Mac"]["firefox"].append(ua)
                elif " Chrome/" in ua:
                    classified["Mac"]["chrome"].append(ua)
                elif " Version/" in ua and " Safari/" in ua:
                    classified["Mac"]["safari"].append(ua)
            elif "Linux" in ua or "X11" in ua:
                if " Firefox/" in ua:
                    classified["Linux"]["firefox"].append(ua)
                elif " Chrome/" in ua:
                    classified["Linux"]["chrome"].append(ua)

        return classified

    @staticmethod
    def write_json_file(file_path: str, payload):
        parent_dir = os.path.dirname(file_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)
            file.write("\n")

    def write_outputs_to_directory(self, target_output_dir: str):
        logger.info(f"💾 写出目录: {target_output_dir}")
        classified = self.classify_user_agents()
        os.makedirs(target_output_dir, exist_ok=True)

        for os_type, browsers in classified.items():
            os_type_dir = os.path.join(target_output_dir, os_type)
            os.makedirs(os_type_dir, exist_ok=True)
            for browser, ua_list in browsers.items():
                if not ua_list:
                    continue
                self.write_json_file(os.path.join(os_type_dir, f"{browser}_all.json"), ua_list)
                self.write_json_file(os.path.join(os_type_dir, f"{browser}_latest50.json"), ua_list[:50])

        self.write_json_file(os.path.join(target_output_dir, "all.json"), self.user_agents)
        self.write_json_file(os.path.join(target_output_dir, "all_latest50.json"), self.user_agents[:50])
        self.write_json_file(os.path.join(target_output_dir, "current.json"), self.current_user_agents)
        self.write_json_file(os.path.join(target_output_dir, "metadata.json"), self.current_metadata)

    def stage_publication(self) -> tuple[str, str]:
        staging_root = tempfile.mkdtemp(prefix="publish-", dir=os.getcwd())
        staged_output_dir = os.path.join(staging_root, self.output_dir)
        staged_snapshot_path = os.path.join(staging_root, self.snapshot_name)

        logger.info(f"🧪 在临时目录构建发布结果: {staging_root}")
        self.write_outputs_to_directory(staged_output_dir)
        self.write_json_file(staged_snapshot_path, self.build_snapshot_payload())
        return staging_root, staged_snapshot_path

    def publish_atomically(self, staging_root: str, staged_snapshot_path: str):
        backup_output_dir = None
        staged_output_dir = os.path.join(staging_root, self.output_dir)
        final_snapshot_path = os.path.join(self.snapshots_dir, self.snapshot_name)

        try:
            if os.path.isdir(self.output_dir):
                backup_output_dir = f"{self.output_dir}.backup-{self.snapshot_name.removesuffix('.json')}"
                if os.path.exists(backup_output_dir):
                    shutil.rmtree(backup_output_dir)
                os.replace(self.output_dir, backup_output_dir)
                logger.info(f"🛟 已备份当前 output 目录: {backup_output_dir}")

            os.replace(staged_output_dir, self.output_dir)
            logger.info(f"🚚 已切换最新 output 目录: {self.output_dir}")

            os.makedirs(self.snapshots_dir, exist_ok=True)
            os.replace(staged_snapshot_path, final_snapshot_path)
            logger.info(f"🗂️ 已发布快照: {final_snapshot_path}")
        except Exception:
            if os.path.isdir(self.output_dir):
                shutil.rmtree(self.output_dir)
            if backup_output_dir and os.path.isdir(backup_output_dir):
                os.replace(backup_output_dir, self.output_dir)
                logger.warning("↩️ 发布失败，已恢复上次成功的 output 目录")
            raise
        else:
            if backup_output_dir and os.path.isdir(backup_output_dir):
                shutil.rmtree(backup_output_dir)
        finally:
            if os.path.isdir(staging_root):
                shutil.rmtree(staging_root)

    def run(self):
        self.generate_current_user_agents()
        self.user_agents = self.load_history_user_agents()
        logger.info(f"📚 历史唯一 User-Agent 共 {len(self.user_agents)} 条")
        staging_root, staged_snapshot_path = self.stage_publication()
        self.publish_atomically(staging_root, staged_snapshot_path)
        logger.info(f"✅ 完成！结果已安全发布到 {self.output_dir}")


if __name__ == "__main__":
    UserAgents().run()
