import os
import json
from git import Repo
import tempfile
import uuid
from loguru import logger


class UserAgents:
    def __init__(self, repo_path: str, output_dir: str):
        self.repo_path = repo_path
        self.output_dir = output_dir
        self.user_agents = []

    @staticmethod
    def remove_duplicates(lst: list) -> list:
        """
        去除列表中的重复元素，保留首次出现的元素
        :param lst: 输入列表
        :return: 去重后的列表
        """
        return list(dict.fromkeys(lst))

    def extract_user_agents(self):
        """
        从git仓库的每个commit中提取user-agents.json文件内容，合并并去重后保存到新文件
        """
        repo_tmp_path = os.path.join(tempfile.gettempdir(), uuid.uuid4().hex)
        logger.info(f"📥 克隆仓库 {self.repo_path} 到临时目录{repo_tmp_path}")
        repo = Repo.clone_from(self.repo_path, repo_tmp_path)

        logger.info(f"✨ 开始获取 {self.repo_path} 的历史版本...")
        for i, commit in enumerate(repo.iter_commits()):
            logger.debug(
                f"🚀 ({i + 1}/{len(list(repo.iter_commits()))}/{len(self.user_agents)}) Processing commit {commit.hexsha}...")
            try:
                # 获取commit中的user-agents.json文件内容
                file_content = commit.tree / "user-agents.json"
                if file_content:
                    data = json.loads(file_content.data_stream.read().decode('utf-8'))
                    if isinstance(data, list):
                        self.user_agents += data
                self.user_agents = self.remove_duplicates(self.user_agents)
            except Exception as e:
                logger.error(f"❌ {commit.hexsha} - 失败: {str(e)}")

        logger.info(f"🎉 共获取 {len(self.user_agents)} 条唯一 User-Agent 记录")

    def classify_user_agents(self) -> dict:
        """
        将User-Agent按操作系统和浏览器分类
        :return:
        """
        classified = {
            'Windows': {'chrome': [], 'firefox': [], 'edge': []},
            'Mac': {'chrome': [], 'firefox': [], 'safari': []},
            'Linux': {'chrome': [], 'firefox': []}
        }

        logger.info("🔄 开始分类 User-Agent...")
        for ua in self.user_agents:
            if 'Windows' in ua:
                if 'Chrome' in ua:
                    classified['Windows']['chrome'].append(ua)
                elif 'Firefox' in ua:
                    classified['Windows']['firefox'].append(ua)
                elif 'Edg' in ua:
                    classified['Windows']['edge'].append(ua)
            elif 'Macintosh' in ua:
                if 'Chrome' in ua:
                    classified['Mac']['chrome'].append(ua)
                elif 'Firefox' in ua:
                    classified['Mac']['firefox'].append(ua)
                elif 'Safari' in ua:
                    classified['Mac']['safari'].append(ua)
            elif 'Linux' in ua or 'X11' in ua:
                if 'Chrome' in ua:
                    classified['Linux']['chrome'].append(ua)
                elif 'Firefox' in ua:
                    classified['Linux']['firefox'].append(ua)

        logger.info("✨ 分类完成, 保存分类结果...")
        # 创建输出目录
        os.makedirs(self.output_dir, exist_ok=True)
        # 保存分类结果
        for os_type, browsers in classified.items():
            os_type_dir = os.path.join(self.output_dir, os_type)
            os.makedirs(os_type_dir, exist_ok=True)

            for browser, ua_list in browsers.items():
                if ua_list:  # 只保存非空列表
                    # 全部记录
                    with open(f'{os_type_dir}/{browser}_all.json', 'w') as f:
                        json.dump(ua_list, f, indent=2)

                    # 最新50条记录
                    with open(f'{os_type_dir}/{browser}_latest50.json', 'w') as f:
                        json.dump(ua_list[:50], f, indent=2)

        # 保存所有 User-Agent 记录
        with open(f'{self.output_dir}/all.json', 'w') as f:
            json.dump(self.user_agents, f, indent=2)

        # 保存最新的 50 条 User-Agent 记录
        with open(f'{self.output_dir}/all_latest50.json', 'w') as f:
            json.dump(self.user_agents[:50], f, indent=2)

        logger.info(f"🎉 完成！分类结果已保存到 {self.output_dir} 目录")


if __name__ == "__main__":
    u = UserAgents(
        repo_path="https://github.com/jnrbsn/user-agents",  # git仓库路径
        output_dir="output"  # 输出目录
    )

    u.extract_user_agents()
    u.classify_user_agents()
