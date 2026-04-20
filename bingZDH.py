import json
import time
import logging
import random
import os
import tempfile
import requests
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ========== 配置模块 ==========
WAIT_TIMEOUT = 20
IS_GITHUB_ACTIONS = os.getenv('GITHUB_ACTIONS') == 'true'
# 在 CI 环境下，强制开启无头模式
HEADLESS = True 

# 日志配置
LOG_FILE = "/tmp/bing_automation.log" if IS_GITHUB_ACTIONS else "bing_automation.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ========== 核心功能函数 ==========

def get_bing_hotwords():
    """
    修复：获取 Bing 热搜词作为搜索来源
    """
    logger.info("正在获取 Bing 热搜词...")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # 从 Bing 首页获取搜索建议或使用公共接口
        resp = requests.get("https://www.bing.com/AS/Suggestions?pt=page.home&mkt=zh-cn&qry=a", headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        words = [li.get_text() for li in soup.find_all('li')]
        
        # 如果爬取失败，使用兜底词库
        if not words or len(words) < 5:
            words = ["今日天气", "GitHub 教程", "Python 自动化", "AI 新闻", "必应奖励", "微软商城", "每日英语"]
        
        logger.info(f"成功获取 {len(words)} 个搜索词")
        return words
    except Exception as e:
        logger.warning(f"获取热词失败，使用默认词库: {e}")
        return ["Bing Rewards", "Microsoft Azure", "Xbox Game Pass", "Edge Browser", "Windows 11"]

def get_driver(email):
    """
    配置并启动浏览器
    """
    options = uc.ChromeOptions()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    
    # 自动定位 Chrome 二进制文件
    chrome_bin = os.getenv('CHROME_BIN')
    if chrome_bin:
        options.binary_location = chrome_bin

    # 使用临时目录存放 User Data，防止多账号冲突
    user_data = tempfile.mkdtemp(prefix=f"chrome_user_{email.split('@')[0]}_")
    options.add_argument(f'--user-data-dir={user_data}')

    try:
        driver = uc.Chrome(options=options, headless=HEADLESS)
        driver.set_page_load_timeout(60)
        return driver
    except Exception as e:
        logger.error(f"浏览器启动失败: {e}")
        return None

def handle_login(driver, email, password):
    """
    处理登录流程及各种弹窗
    """
    logger.info(f"开始登录: {email}")
    driver.get("https://login.live.com/")
    
    try:
        # 输入邮箱
        wait = WebDriverWait(driver, WAIT_TIMEOUT)
        email_field = wait.until(EC.presence_of_element_located((By.NAME, "loginfmt")))
        email_field.send_keys(email)
        driver.find_element(By.ID, "idSIButton9").click()
        
        # 输入密码
        time.sleep(2)
        password_field = wait.until(EC.element_to_be_clickable((By.NAME, "passwd")))
        password_field.send_keys(password)
        driver.find_element(By.ID, "idSIButton9").click()
        
        # 处理“保持登录”或“通行密钥”弹窗
        time.sleep(3)
        for _ in range(3):
            try:
                # 查找常见的“是”、“确定”、“跳过”按钮
                btns = driver.find_elements(By.XPATH, "//input[@value='是'] | //input[@value='Yes'] | //button[contains(text(), '确定')] | //button[contains(text(), 'Skip')]")
                if btns:
                    btns[0].click()
                    time.sleep(2)
            except:
                break
        return True
    except Exception as e:
        logger.error(f"登录执行出错: {e}")
        return False

def click_reward_tasks(driver):
    """
    修复：点击 Rewards 页面的每日任务卡片
    """
    logger.info("开始处理每日任务卡片...")
    driver.get("https://rewards.bing.com/")
    time.sleep(5)
    
    try:
        # 获取所有任务磁贴
        tasks = driver.find_elements(By.CSS_SELECTOR, "div[data-bi-id]")
        for i, task in enumerate(tasks[:5]): # 每天处理前 5 个未完成任务
            try:
                # 检查是否已完成 (通常有 checkmark 类名)
                if "complete" in task.get_attribute("class").lower():
                    continue
                
                logger.info(f"点击第 {i+1} 个任务卡片")
                driver.execute_script("arguments[0].click();", task)
                time.sleep(3)
                # 切换回主页面（如果开了新标签页）
                if len(driver.window_handles) > 1:
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
            except:
                continue
    except Exception as e:
        logger.warning(f"任务卡片处理出现部分异常: {e}")

def run_search(driver, words):
    """
    执行搜索任务
    """
    search_count = 35 if not IS_GITHUB_ACTIONS else 40 # 稍微多搜几次确保加分
    selected_words = random.sample(words, min(len(words), search_count))
    
    for i, word in enumerate(selected_words):
        try:
            logger.info(f"[{i+1}/{len(selected_words)}] 搜索: {word}")
            driver.get(f"https://www.bing.com/search?q={requests.utils.quote(word)}")
            # 随机停留模拟真实人类
            time.sleep(random.uniform(5, 12)) 
        except Exception as e:
            logger.error(f"单次搜索失败: {e}")

# ========== 主程序流程 ==========

def process_account(acc, words):
    driver = get_driver(acc['email'])
    if not driver: return
    
    try:
        if handle_login(driver, acc['email'], acc['password']):
            # 1. 刷任务卡片
            click_reward_tasks(driver)
            # 2. 刷搜索分数
            run_search(driver, words)
            logger.info(f"账号 {acc['email']} 任务全部完成！")
    finally:
        driver.quit()

def main():
    # 加载配置
    config_path = 'config/accounts.json'
    if not os.path.exists(config_path):
        logger.error(f"找不到配置文件: {config_path}")
        return

    with open(config_path, 'r', encoding='utf-8') as f:
        account_groups = json.load(f)

    # 修复：确保调用已定义的函数
    words = get_bing_hotwords()

    # 在 GitHub Actions 中按顺序处理，避免 CPU 崩溃
    for group_name, accounts in account_groups.items():
        logger.info(f">>> 开始处理分组: {group_name}")
        for acc in accounts:
            process_account(acc, words)
            time.sleep(5)

if __name__ == "__main__":
    main()
