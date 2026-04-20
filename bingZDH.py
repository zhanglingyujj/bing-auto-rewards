import json
import time
import logging
import random
import re
import os
import datetime
import tempfile
import threading
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import requests
from bs4 import BeautifulSoup

# ========== 核心配置优化 ==========
WAIT_TIMEOUT = 20
RETRY_COUNT = 2
BING_URL = "https://www.bing.com"
REWARDS_URL = "https://rewards.bing.com/"

# 环境检测
IS_GITHUB_ACTIONS = os.getenv('GITHUB_ACTIONS') == 'true'
HEADLESS = True  # 强制使用无头模式
LOG_FILE = "/tmp/bing_automation.log" if IS_GITHUB_ACTIONS else "bing_automation.log"

# 根据环境动态调整搜索节奏
if IS_GITHUB_ACTIONS:
    SLEEP_BETWEEN_SEARCH = (3, 8)
    SLEEP_AFTER_4_SEARCH = 60 # CI 环境不需要停太久，浪费额度
else:
    SLEEP_BETWEEN_SEARCH = (10, 25)
    SLEEP_AFTER_4_SEARCH = 600

# ========== 日志配置 ==========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== 通用工具函数 ==========

def get_driver(group_name):
    """
    创建并返回配置优化的 undetected_chromedriver 实例
    """
    options = uc.ChromeOptions()
    # 基础稳定选项
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    
    # 自动识别 GitHub Actions 中的 Chrome 路径
    chrome_bin = os.getenv('CHROME_BIN')
    if chrome_bin:
        options.binary_location = chrome_bin

    # 隐私与反检测
    options.add_argument('--incognito')
    options.add_argument('--disable-blink-features=AutomationControlled')
    
    # 使用临时文件夹存放用户数据，避免进程冲突
    tmp_user_data = tempfile.mkdtemp(prefix=f"chrome_user_{group_name}_")
    options.add_argument(f'--user-data-dir={tmp_user_data}')

    try:
        # 在 CI 环境中，browser_executable_path 是关键
        driver = uc.Chrome(
            options=options,
            headless=HEADLESS,
            version_main=None # 自动匹配
        )
        # 设置页面加载超时
        driver.set_page_load_timeout(60)
        return driver
    except Exception as e:
        logger.error(f"启动 Chrome 失败: {e}")
        return None

def smart_wait_click(driver, locator, timeout=WAIT_TIMEOUT):
    """智能等待并点击，带重试逻辑"""
    for _ in range(2):
        try:
            element = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(locator))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.5)
            element.click()
            return True
        except Exception:
            try:
                # 备选方案：JS 点击
                element = driver.find_element(*locator)
                driver.execute_script("arguments[0].click();", element)
                return True
            except:
                continue
    return False

# ========== 业务逻辑优化 ==========

def handle_interruptions(driver):
    """
    集中处理登录过程中的各种干扰项：保持登录、通行密钥、隐私确认
    """
    interrupt_selectors = [
        "//button[contains(text(), '暂时跳过')]",
        "//button[contains(text(), 'Skip for now')]",
        "//input[@value='是']",
        "//input[@value='Yes']",
        "//button[@id='idSIButton9']", # 通用的“下一步/提交” ID
        "//button[contains(@class, 'primary')]"
    ]
    
    for _ in range(5): # 最多尝试处理5个连续干扰
        try:
            time.sleep(2)
            found = False
            for xpath in interrupt_selectors:
                btns = driver.find_elements(By.XPATH, xpath)
                for b in btns:
                    if b.is_displayed():
                        b.click()
                        logger.info(f"处理干扰项成功: {xpath}")
                        found = True
                        break
                if found: break
            if not found: break
        except:
            break

def login_bing(driver, email, password):
    logger.info(f"尝试登录账号: {email}")
    driver.get("https://login.live.com/")
    
    # 输入邮箱
    try:
        email_input = WebDriverWait(driver, WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.NAME, "loginfmt"))
        )
        email_input.send_keys(email)
        smart_wait_click(driver, (By.ID, "idSIButton9"))
    except Exception as e:
        logger.error(f"输入邮箱阶段失败: {e}")
        return False

    # 输入密码
    try:
        pass_input = WebDriverWait(driver, WAIT_TIMEOUT).until(
            EC.element_to_be_clickable((By.NAME, "passwd"))
        )
        pass_input.send_keys(password)
        time.sleep(1)
        smart_wait_click(driver, (By.ID, "idSIButton9"))
    except Exception as e:
        logger.info(f"密码输入失败，可能需要验证码或已经登录: {e}")

    # 处理后续弹窗
    handle_interruptions(driver)
    
    # 验证是否到达 Bing 或 Rewards
    driver.get(BING_URL)
    time.sleep(3)
    return "id_s" in driver.page_source or "meControl" in driver.page_source

def search_loop(driver, words):
    """
    优化的搜索逻辑
    """
    for i, word in enumerate(words):
        try:
            driver.get(f"{BING_URL}/search?q={requests.utils.quote(word)}")
            logger.info(f"搜索 [{i+1}/{len(words)}]: {word}")
            
            # 模拟真实浏览：随机滚动
            if random.random() > 0.5:
                driver.execute_script(f"window.scrollTo(0, {random.randint(300, 800)});")
            
            time.sleep(random.uniform(*SLEEP_BETWEEN_SEARCH))
            
            if (i + 1) % 4 == 0:
                logger.info("短暂停顿以模拟真人行为...")
                time.sleep(5)
                
        except Exception as e:
            logger.error(f"搜索词 {word} 时出错: {e}")
            continue

# ========== 执行框架 ==========

def process_account(account, words):
    """
    处理单个账号的完整生命周期
    """
    email = account.get('email')
    driver = get_driver(email)
    if not driver: return

    try:
        if login_bing(driver, email, account.get('password')):
            logger.info(f"账号 {email} 登录成功")
            
            # 1. 签到与任务
            driver.get(REWARDS_URL)
            time.sleep(5)
            # 这里可以调用你原有的 click_reward_tasks
            
            # 2. 执行搜索
            # 随机选取一部分词进行搜索，避免行为过于固定
            selected_words = random.sample(words, min(len(words), 35))
            search_loop(driver, selected_words)
            
        else:
            logger.error(f"账号 {email} 登录失败")
    except Exception as e:
        logger.error(f"账号 {email} 执行异常: {e}")
    finally:
        try:
            driver.quit()
        except:
            pass

def main():
    # 读取配置
    try:
        with open('config/accounts.json', 'r', encoding='utf-8') as f:
            account_groups = json.load(f)
    except FileNotFoundError:
        logger.error("配置文件 accounts.json 未找到！")
        return

    words = get_bing_hotwords()
    
    # 在 GitHub Actions 中，建议 串行 或 极低并发 处理
    # 如果账号组很多，改为串行以保证稳定性
    for group_name, accounts in account_groups.items():
        logger.info(f"开始处理账号组: {group_name}")
        for acc in accounts:
            process_account(acc, words)
            time.sleep(10) # 账号间切换停顿

if __name__ == "__main__":
    main()
