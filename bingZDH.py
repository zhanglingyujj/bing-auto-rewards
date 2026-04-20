import json
import time
import logging
import random
import re
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests
from bs4 import BeautifulSoup
import datetime
import os

# ========== CONFIG ==========
WAIT_TIMEOUT = 15
RETRY_COUNT = 3
BING_URL = "https://www.bing.com"
REWARDS_URL = "https://rewards.bing.com/"
LOG_FILE = "bing_automation.log"
HEADLESS = True  # True为无头模式
SLEEP_BETWEEN_SEARCH = (10, 30)  # 搜索间隔秒数范围
SLEEP_AFTER_4_SEARCH = 960  # 每4次搜索后暂停秒数
MAX_SKIP = 8  # 跳过"创建通行密钥"页面最大尝试次数

# 检查是否在GitHub Actions环境中
if os.getenv('GITHUB_ACTIONS'):
    HEADLESS = True  # GitHub Actions中强制使用无头模式
    # 在GitHub Actions中调整配置
    WAIT_TIMEOUT = 20  # 增加等待时间
    SLEEP_BETWEEN_SEARCH = (5, 15)  # 减少搜索间隔
    SLEEP_AFTER_4_SEARCH = 300  # 减少暂停时间（5分钟）
    # 设置日志文件路径
    LOG_FILE = "/tmp/bing_automation.log"

# ========== LOGGING ==========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== 工具函数 ==========
def check_driver_connection(driver, group_name):
    """检查WebDriver连接是否正常"""
    try:
        # 尝试获取当前URL，如果失败说明连接已断开
        driver.current_url
        return True
    except Exception as e:
        logger.warning(f"账号组 {group_name} WebDriver连接检查失败: {e}")
        return False

def safe_driver_operation(driver, group_name, operation_name, operation_func):
    """安全执行driver操作，如果连接断开则重新创建"""
    try:
        return operation_func()
    except Exception as e:
        if "Failed to establish a new connection" in str(e) or "HTTPConnectionPool" in str(e) or "invalid session id" in str(e):
            logger.warning(f"账号组 {group_name} {operation_name} 时检测到连接问题: {e}")
            return None
        else:
            raise e

def wait_and_click(driver, by, value, timeout=WAIT_TIMEOUT):
    try:
        btn = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, value))
        )
        btn.click()
        return True
    except Exception as e:
        logger.error(f"点击 {value} 失败: {e}")
        return False

def wait_and_type(driver, by, value, text, timeout=WAIT_TIMEOUT):
    try:
        inp = WebDriverWait(driver, timeout).until(
            EC.visibility_of_element_located((by, value))
        )
        inp.clear()
        inp.send_keys(text)
        return True
    except Exception as e:
        logger.error(f"输入 {value} 失败: {e}")
        return False

def robust_wait_and_click(driver, by, value, timeout=WAIT_TIMEOUT, retries=RETRY_COUNT):
    for attempt in range(retries):
        try:
            # 检查连接是否正常
            if not check_driver_connection(driver, "unknown"):
                logger.warning(f"WebDriver连接已断开，无法点击 {value}")
                return False
                
            btn = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((by, value))
            )
            btn.click()
            return True
        except Exception as e:
            # 检查是否是连接问题
            if "Failed to establish a new connection" in str(e) or "HTTPConnectionPool" in str(e) or "invalid session id" in str(e):
                logger.warning(f"WebDriver连接问题，无法继续点击 {value}: {e}")
                return False
                
            logger.warning(f"重试点击 {value} 第{attempt+1}次失败: {e}")
            if attempt < retries - 1:  # 不是最后一次尝试
                time.sleep(2)
            else:
                # 最后一次尝试，截图保存
                try:
                    screenshot_name = f"click_fail_{by}_{value.replace('/', '_').replace(':', '_')}_{int(time.time())}.png"
                    driver.save_screenshot(screenshot_name)
                    logger.info(f"点击失败截图已保存: {screenshot_name}")
                except Exception as screenshot_error:
                    logger.warning(f"截图保存失败: {screenshot_error}")
    return False

def handle_stay_signed_in_popup(driver, idx):
    """
    专门处理"保持登录状态"弹窗的函数
    """
    try:
        # 等待弹窗出现
        time.sleep(3)
        
        # 检查是否有iframe
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            try:
                driver.switch_to.frame(iframe)
                # 在iframe中查找相关元素
                if handle_popup_in_frame(driver):
                    driver.switch_to.default_content()
                    return True
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()
                continue
        
        # 在主文档中处理
        return handle_popup_in_frame(driver)
        
    except Exception as e:
        logger.warning(f"处理'保持登录状态'弹窗失败: {e}")
        return False

def handle_popup_in_frame(driver):
    """
    在指定frame中处理弹窗
    """
    try:
        # 查找"保持登录状态"相关的文本
        stay_signed_texts = [
            "保持登录状态",
            "Stay signed in",
            "保持登录",
            "保持登录状态?",
            "Stay signed in?"
        ]
        
        # 查找包含这些文本的元素
        for text in stay_signed_texts:
            try:
                elements = driver.find_elements(By.XPATH, f"//*[contains(text(), '{text}')]")
                if elements:
                    logger.info(f"找到'保持登录状态'弹窗，文本: {text}")
                    
                    # 查找"是"按钮
                    yes_selectors = [
                        "//button[contains(text(), '是')]",
                        "//button[contains(text(), 'Yes')]",
                        "//input[@value='是']",
                        "//input[@value='Yes']",
                        "//button[contains(@aria-label, '是')]",
                        "//button[contains(@aria-label, 'Yes')]",
                        "//button[contains(@class, 'primary')]",
                        "//button[contains(@class, 'btn-primary')]",
                        "//button[contains(@class, 'ms-Button--primary')]",
                        "//div[contains(@role, 'button') and contains(text(), '是')]",
                        "//div[contains(@role, 'button') and contains(text(), 'Yes')]"
                    ]
                    
                    for selector in yes_selectors:
                        try:
                            yes_btn = WebDriverWait(driver, 3).until(
                                EC.element_to_be_clickable((By.XPATH, selector))
                            )
                            # 滚动到元素位置
                            driver.execute_script("arguments[0].scrollIntoView(true);", yes_btn)
                            time.sleep(0.5)
                            
                            # 尝试点击
                            try:
                                yes_btn.click()
                                logger.info(f"成功点击'是'按钮: {selector}")
                                return True
                            except Exception:
                                try:
                                    driver.execute_script("arguments[0].click();", yes_btn)
                                    logger.info(f"使用JavaScript成功点击'是'按钮: {selector}")
                                    return True
                                except Exception:
                                    continue
                        except Exception:
                            continue
                    
                    # 如果找不到"是"按钮，尝试找"否"按钮
                    no_selectors = [
                        "//button[contains(text(), '否')]",
                        "//button[contains(text(), 'No')]",
                        "//input[@value='否']",
                        "//input[@value='No']"
                    ]
                    
                    for selector in no_selectors:
                        try:
                            no_btn = WebDriverWait(driver, 2).until(
                                EC.element_to_be_clickable((By.XPATH, selector))
                            )
                            driver.execute_script("arguments[0].click();", no_btn)
                            logger.info(f"点击'否'按钮: {selector}")
                            return True
                        except Exception:
                            continue
                            
            except Exception:
                continue
        
        return False
        
    except Exception as e:
        logger.warning(f"在frame中处理弹窗失败: {e}")
        return False

def click_login_button(driver, idx):
    # 1. 先用id
    if robust_wait_and_click(driver, By.ID, "id_l"):
        logger.info("用ID方式点击登录按钮成功")
        return True
    # 2. 用class
    if robust_wait_and_click(driver, By.CSS_SELECTOR, "a.id_button"):
        logger.info("用class方式点击登录按钮成功")
        return True
    # 3. 用多语言文本和aria-label
    xpath = (
        "//a[span[text()='登录'] or span[text()='Sign in'] or span[text()='登入']]"
        "|//a[contains(@aria-label, '登录') or contains(@aria-label, 'Sign in') or contains(@aria-label, '登入')]"
        "|//a[contains(text(), '登录') or contains(text(), 'Sign in') or contains(text(), '登入')]"
        "|//button[span[text()='登录'] or span[text()='Sign in'] or span[text()='登入']]"
        "|//button[contains(@aria-label, '登录') or contains(@aria-label, 'Sign in') or contains(@aria-label, '登入')]"
        "|//button[contains(text(), '登录') or contains(text(), 'Sign in') or contains(text(), '登入')]"
    )
    if robust_wait_and_click(driver, By.XPATH, xpath):
        logger.info("用多语言文本方式点击登录按钮成功")
        return True
    logger.error("所有方式都未能点击登录按钮")
    return False

def get_bing_hotwords():
    logger.info("开始获取热搜关键词...")
    try:
        logger.info("尝试获取百度热搜...")
        resp = requests.get("https://top.baidu.com/board?tab=realtime", timeout=8, proxies={"http": None, "https": None})
        soup = BeautifulSoup(resp.text, "html.parser")
        hotwords = [tag.text.strip() for tag in soup.select(".c-single-text-ellipsis")]
        if hotwords:
            logger.info(f"已获取百度热搜词：{hotwords[:40]}")
            return hotwords[:40]
    except Exception as e:
        logger.warning(f"获取百度热搜失败：{e}")
    try:
        logger.info("尝试获取微博热搜...")
        resp = requests.get("https://s.weibo.com/top/summary", timeout=8, proxies={"http": None, "https": None})
        soup = BeautifulSoup(resp.text, "html.parser")
        hotwords = [tag.text.strip() for tag in soup.select(".td-02 a") if tag.text.strip()]
        if hotwords:
            logger.info(f"已获取微博热搜词：{hotwords[:40]}")
            return hotwords[:40]
    except Exception as e:
        logger.warning(f"获取微博热搜失败：{e}")
    logger.info("使用默认搜索关键词")
    return [
        "python", "bing", "ai", "chatgpt", "微软", "天气", "NBA", "世界杯", "科技新闻", "人工智能",
        "股票", "电影", "电视剧", "旅游", "健康", "教育", "汽车", "手机", "数码", "美食", "历史", "地理", "音乐", "游戏", "动漫"
    ]



# ========== 业务逻辑 ==========
def login_bing(driver, email, password, idx, group_name=None):
    # 检查WebDriver连接
    if group_name and not check_driver_connection(driver, group_name):
        raise Exception("WebDriver连接已断开")
    
    max_page_retry = 3  # 页面整体重试次数
    for page_try in range(max_page_retry):
        logger.info(f"第{page_try+1}次尝试登录...")
        driver.get(BING_URL)
        time.sleep(3)  # 增加等待时间
        
        if not click_login_button(driver, idx):
            raise Exception("未找到登录按钮")
        
        # 等待新窗口打开
        time.sleep(3)
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])
            logger.info("已切换到登录窗口")
        
        # 等待页面加载
        time.sleep(3)
        
        # 尝试多种方式找到邮箱输入框
        email_entered = False
        email_selectors = [
            (By.ID, "usernameEntry"),
            (By.NAME, "loginfmt"),
            (By.ID, "i0116"),
            (By.NAME, "email"),
            (By.CSS_SELECTOR, "input[type='email']"),
            (By.XPATH, "//input[@type='email']"),
            (By.XPATH, "//input[contains(@placeholder, '邮箱') or contains(@placeholder, 'email')]")
        ]
        
        for selector_type, selector_value in email_selectors:
            try:
                logger.info(f"尝试使用选择器: {selector_type} = {selector_value}")
                if wait_and_type(driver, selector_type, selector_value, email):
                    email_entered = True
                    logger.info(f"成功输入邮箱，使用选择器: {selector_type} = {selector_value}")
                    break
                time.sleep(2)
            except Exception as e:
                logger.warning(f"选择器 {selector_type} = {selector_value} 失败: {e}")
                continue
        
        if email_entered:
            break  # 成功输入邮箱，跳出大循环
        else:
            logger.warning(f"第{page_try+1}次页面加载未找到邮箱输入框，刷新页面重试...")
            driver.refresh()
            time.sleep(5)
    else:
        logger.error("多次刷新页面后仍未找到邮箱输入框，跳过该账号。")
        raise Exception("未找到邮箱输入框")
    if not robust_wait_and_click(driver, By.CSS_SELECTOR, "button[data-testid='primaryButton']"):
        raise Exception("未找到下一个按钮")
    
    # 处理可能的验证码页面
    time.sleep(3)
    try:
        # 检查是否出现验证码页面
        page_text = driver.page_source
        if "获取用于登录的代码" in page_text or "发送验证码" in page_text:
            logger.info("检测到验证码页面，尝试点击'使用密码'按钮")
            try:
                # 尝试多种方式找到"使用密码"按钮
                password_buttons = [
                    (By.XPATH, "//*[text()='使用密码']"),
                    (By.XPATH, "//*[text()='Use password']"),
                    (By.XPATH, "//button[contains(text(), '使用密码')]"),
                    (By.XPATH, "//button[contains(text(), 'Use password')]"),
                    (By.XPATH, "//a[contains(text(), '使用密码')]"),
                    (By.XPATH, "//a[contains(text(), 'Use password')]"),
                    (By.CSS_SELECTOR, "button[data-testid='secondaryButton']"),
                    (By.CSS_SELECTOR, "a[data-testid='secondaryButton']")
                ]
                
                for btn_type, btn_value in password_buttons:
                    try:
                        if robust_wait_and_click(driver, btn_type, btn_value, timeout=3):
                            logger.info(f"成功点击'使用密码'按钮: {btn_type} = {btn_value}")
                            time.sleep(3)
                            break
                    except Exception:
                        continue
                else:
                    logger.warning("未找到'使用密码'按钮，尝试继续...")
            except Exception as e:
                logger.warning(f"处理验证码页面失败: {e}")
    except Exception as e:
        logger.warning(f"检查验证码页面失败: {e}")
    
    for _ in range(MAX_SKIP):
        time.sleep(1)
        current_url = driver.current_url
        
        # 检查是否已经到达密码输入页面
        try:
            password_field = driver.find_element(By.NAME, "passwd")
            if password_field.is_displayed():
                logger.info("检测到密码输入页面，跳出通行密钥处理循环")
                break
        except Exception:
            pass
        
        # 检查是否已经到达Bing主页
        if "bing.com" in current_url and not any(x in current_url for x in ["setup", "create", "auth"]):
            logger.info("已到达Bing主页，跳出通行密钥处理循环")
            break
        try:
            skip_btn = WebDriverWait(driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, "//*[text()='暂时跳过']"))
            )
            skip_btn.click()
            logger.info("检测到‘创建通行密钥’页面，已点击‘暂时跳过’。")
            continue
        except Exception:
            pass
        try:
            next_btn = WebDriverWait(driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, "//*[text()='下一个']"))
            )
            next_btn.click()
            logger.info("检测到‘创建通行密钥’页面，已点击‘下一个’。")
            continue
        except Exception:
            pass
        if "setup" in current_url or "create" in current_url:
            logger.warning("检测到setup/create页面，强制跳转到bing主页。")
            driver.get(BING_URL)
            time.sleep(2)
            break
    try:
        WebDriverWait(driver, WAIT_TIMEOUT).until(
            EC.invisibility_of_element_located((By.ID, "usernameEntry"))
        )
    except Exception:
        pass
    try:
        # 增强密码输入框查找逻辑，循环多种方式，延长等待时间
        password_input = None
        for _ in range(WAIT_TIMEOUT * 2):  # 最多等30秒
            try:
                password_input = driver.find_element(By.NAME, "passwd")
                if password_input.is_displayed():
                    break
            except Exception:
                pass
            try:
                password_input = driver.find_element(By.ID, "passwordEntry")
                if password_input.is_displayed():
                    break
            except Exception:
                pass
            time.sleep(1)
        if not password_input or not password_input.is_displayed():
            raise Exception("未找到密码输入框")
    except Exception as e:
        logger.error("未找到密码输入框")
        raise Exception("未找到密码输入框")
    password_input.clear()
    password_input.send_keys(password)
    # 尝试点击登录/下一个按钮
    login_success = False
    login_buttons = [
        (By.CSS_SELECTOR, "button[data-testid='primaryButton']"),
        (By.XPATH, "//*[text()='登录']"),
        (By.XPATH, "//*[text()='下一个']"),
        (By.XPATH, "//input[@type='submit']"),
        (By.XPATH, "//button[@type='submit']")
    ]
    
    for btn_type, btn_value in login_buttons:
        try:
            if robust_wait_and_click(driver, btn_type, btn_value):
                logger.info(f"成功点击登录按钮: {btn_type} = {btn_value}")
                login_success = True
                break
        except Exception as e:
            logger.warning(f"点击登录按钮失败 {btn_type} = {btn_value}: {e}")
            continue
    
    if not login_success:
        logger.warning("未找到登录按钮，尝试继续...")
    
    # 处理可能的"创建通行密钥"页面
    try:
        time.sleep(2)
        current_url = driver.current_url
        page_text = driver.page_source
        
        # 检查是否在"创建通行密钥"页面
        if "创建通行密钥" in page_text or ("passkey" in page_text.lower() and "创建" in page_text) or "使用人脸、指纹或PIN" in page_text:
            logger.info("检测到通行密钥页面，尝试点击'暂时跳过'")
            try:
                # 尝试多种方式找到"暂时跳过"按钮
                skip_buttons = [
                    (By.XPATH, "//*[text()='暂时跳过']"),
                    (By.XPATH, "//*[text()='Skip for now']"),
                    (By.XPATH, "//button[contains(text(), '暂时跳过')]"),
                    (By.XPATH, "//button[contains(text(), 'Skip for now')]"),
                    (By.XPATH, "//a[contains(text(), '暂时跳过')]"),
                    (By.XPATH, "//a[contains(text(), 'Skip for now')]"),
                    (By.CSS_SELECTOR, "button[data-testid='secondaryButton']"),
                    (By.CSS_SELECTOR, "a[data-testid='secondaryButton']"),
                    (By.XPATH, "//button[contains(@class, 'secondary')]"),
                    (By.XPATH, "//button[contains(@class, 'skip')]")
                ]
                
                skip_clicked = False
                for btn_type, btn_value in skip_buttons:
                    try:
                        # 先尝试普通点击
                        if robust_wait_and_click(driver, btn_type, btn_value, timeout=2):
                            logger.info(f"成功点击'暂时跳过'按钮: {btn_type} = {btn_value}")
                            skip_clicked = True
                            break
                    except Exception:
                        continue
                
                # 如果普通点击失败，尝试JavaScript点击
                if not skip_clicked:
                    for btn_type, btn_value in skip_buttons:
                        try:
                            element = driver.find_element(btn_type, btn_value)
                            if element.is_displayed() and element.is_enabled():
                                driver.execute_script("arguments[0].click();", element)
                                logger.info(f"通过JavaScript成功点击'暂时跳过'按钮: {btn_type} = {btn_value}")
                                skip_clicked = True
                                break
                        except Exception:
                            continue
                
                if skip_clicked:
                    time.sleep(3)
                else:
                    logger.warning("所有方式都未能点击'暂时跳过'按钮")
                    
            except Exception as e:
                logger.warning(f"处理通行密钥页面失败: {e}")
        
        # 检查是否出现"保持登录状态"弹窗
        if "保持登录状态" in page_text or "Stay signed in" in page_text:
            logger.info("检测到'保持登录状态'弹窗，尝试点击'是'")
            try:
                yes_buttons = [
                    (By.XPATH, "//*[text()='是']"),
                    (By.XPATH, "//*[text()='Yes']"),
                    (By.XPATH, "//button[contains(text(), '是')]"),
                    (By.XPATH, "//button[contains(text(), 'Yes')]"),
                    (By.XPATH, "//input[@value='是']"),
                    (By.XPATH, "//input[@value='Yes']")
                ]
                
                for btn_type, btn_value in yes_buttons:
                    try:
                        # 使用更短的超时时间，快速尝试
                        if robust_wait_and_click(driver, btn_type, btn_value, timeout=2):
                            logger.info(f"成功点击'是'按钮: {btn_type} = {btn_value}")
                            break
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"点击'是'按钮失败: {e}")
        else:
            # 尝试点击"是"按钮（如果存在）
            try:
                yes_buttons = [
                    (By.XPATH, "//*[text()='是']"),
                    (By.XPATH, "//*[text()='Yes']"),
                    (By.XPATH, "//button[contains(text(), '是')]"),
                    (By.XPATH, "//button[contains(text(), 'Yes')]"),
                    (By.XPATH, "//input[@value='是']"),
                    (By.XPATH, "//input[@value='Yes']")
                ]
                
                for btn_type, btn_value in yes_buttons:
                    try:
                        # 使用更短的超时时间，快速尝试
                        if robust_wait_and_click(driver, btn_type, btn_value, timeout=2):
                            logger.info(f"成功点击'是'按钮: {btn_type} = {btn_value}")
                            break
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"点击'是'按钮失败: {e}")
        
        # 检查是否已经登录成功
        if "bing.com" in current_url:
            logger.info(f"账号{email}登录成功！当前页面: {current_url}")
        else:
            logger.info(f"账号{email}登录流程完成！当前页面: {current_url}")
    except Exception as e:
        logger.warning(f"检查登录状态失败: {e}")
    
    time.sleep(1)

def sign_in_rewards(driver, idx, email, group_name=None):
    # 检查WebDriver连接
    if group_name and not check_driver_connection(driver, group_name):
        raise Exception("WebDriver连接已断开")
    
    driver.get(REWARDS_URL)
    time.sleep(5)
    logger.info(f"账号{email}已访问Rewards页面。")
    try:
        sign_btns = driver.find_elements(By.XPATH, "//button[contains(., '签到') or contains(., 'Sign in') or contains(., 'Check-in')]")
        for btn in sign_btns:
            if btn.is_displayed() and btn.is_enabled():
                btn.click()
                logger.info(f"账号{email}已自动签到。")
                time.sleep(2)
                break
    except Exception as e:
        logger.warning(f"账号{email}自动签到失败: {e}")

def click_reward_tasks(driver, idx, email, group_name=None):
    # 检查WebDriver连接
    if group_name and not check_driver_connection(driver, group_name):
        raise Exception("WebDriver连接已断开")
    
    logger.info(f"账号{email} 开始自动点击积分任务卡片...")
    driver.get(REWARDS_URL)
    time.sleep(5)
    try:
        cards = driver.find_elements(By.CSS_SELECTOR, '.c-card-content a')
        filtered_cards = []
        for card in cards:
            try:
                icon = card.find_element(By.CSS_SELECTOR, '.mee-icon-AddMedium')
                filtered_cards.append(card)
            except Exception:
                continue
        logger.info(f'账号{email} 找到 {len(filtered_cards)} 个可点击的积分任务卡片')
        for i, card in enumerate(filtered_cards):
            try:
                original_window = driver.current_window_handle
                before_handles = driver.window_handles
                
                # 使用JavaScript点击来避免元素遮挡问题
                driver.execute_script("arguments[0].click();", card)
                logger.info(f'账号{email} 已点击第 {i+1} 个任务卡片')
                time.sleep(10)
                
                after_handles = driver.window_handles
                if len(after_handles) > len(before_handles):
                    new_window = [h for h in after_handles if h not in before_handles][0]
                    driver.switch_to.window(new_window)
                    driver.close()
                    driver.switch_to.window(original_window)
                    logger.info(f'账号{email} 已关闭新打开的任务窗口')
            except Exception as e:
                logger.warning(f'账号{email} 点击第 {i+1} 个任务卡片失败: {e}')
                # 如果JavaScript点击失败，尝试滚动到元素位置再点击
                try:
                    driver.execute_script("arguments[0].scrollIntoView(true);", card)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", card)
                    logger.info(f'账号{email} 通过滚动后成功点击第 {i+1} 个任务卡片')
                except Exception as e2:
                    logger.warning(f'账号{email} 滚动后点击第 {i+1} 个任务卡片仍然失败: {e2}')
        if not filtered_cards:
            logger.info(f'账号{email} 没有可点击的积分任务卡片')
    except Exception as e:
        logger.error(f'账号{email} 自动点击积分任务卡片异常: {e}')

def get_bing_points(driver):
    driver.get(REWARDS_URL)
    time.sleep(8)
    page = driver.page_source
    # 总积分
    match_total = re.search(r'"availablePoints"\s*:\s*(\d+)', page)
    if match_total:
        total_points = match_total.group(1)
    else:
        total_points = '未找到总积分'
    # 今日积分
    soup = BeautifulSoup(page, "html.parser")
    today_points = '未找到今日积分'
    for p in soup.find_all("p", attrs={"title": "今日积分"}):
        span = p.find_next("span", attrs={"aria-label": True})
        if span and span.get("aria-label") and span.get("aria-label").strip().isdigit():
            today_points = span.get("aria-label").strip()
            break
    logger.info(f"当前Bing总积分：{total_points}，今日积分：{today_points}")
    return total_points, today_points

def get_pc_search_progress(driver):
    driver.get(REWARDS_URL)
    try:
        detail_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.LINK_TEXT, "积分明细"))
        )
        detail_btn.click()
        time.sleep(8)  # 等待弹窗内容完全渲染
        page = driver.page_source
        soup = BeautifulSoup(page, "html.parser")
        current, total = None, None
        # 找到所有文本为“电脑搜索”的<a>
        for a in soup.find_all("a"):
            if a.get_text(strip=True) == "电脑搜索":
                # 找到下一个class包含pointsDetail的<p>
                p = a.find_parent().find_next("p", class_="pointsDetail")
                if p:
                    b = p.find("b")
                    if b and b.get_text(strip=True).isdigit():
                        current = b.get_text(strip=True)
                        match = re.search(r"/\s*(\d+)", p.get_text())
                        if match:
                            total = match.group(1)
                            logger.info(f"电脑搜索进度：{current} / {total}")
                            return current, total
        logger.warning("未找到电脑搜索进度")
        return None, None
    except Exception as e:
        logger.error(f"获取电脑搜索进度失败：{e}", exc_info=True)
        return None, None

def search_for_points(driver, idx, email, search_words, group_name=None):
    # 检查WebDriver连接
    if group_name and not check_driver_connection(driver, group_name):
        raise Exception("WebDriver连接已断开")
    
    for i, word in enumerate(search_words):
        try:
            random_delay = random.randint(*SLEEP_BETWEEN_SEARCH)
            logger.info(f"等待 {random_delay} 秒后进行第 {i+1} 次搜索...")
            time.sleep(random_delay)
            if (i + 1) % 5 == 0:
                logger.info(f"已完成4次搜索，暂停{SLEEP_AFTER_4_SEARCH//60}分钟...")
                time.sleep(SLEEP_AFTER_4_SEARCH)
            driver.get(BING_URL)
            search_box = WebDriverWait(driver, 10).until(
                EC.visibility_of_element_located((By.NAME, "q"))
            )
            search_box.clear()
            search_box.send_keys(word)
            search_box.submit()
            logger.info(f"账号{email} 搜索：{word}")
            if random.random() < 0.3:
                try:
                    first_result = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "li.b_algo h2 a"))
                    )
                    original_window = driver.current_window_handle
                    before_handles = driver.window_handles
                    first_result.click()
                    time.sleep(random.uniform(5, 10))
                    after_handles = driver.window_handles
                    if len(after_handles) > len(before_handles):
                        new_window = [h for h in after_handles if h not in before_handles][0]
                        driver.switch_to.window(new_window)
                        driver.close()
                        driver.switch_to.window(original_window)
                    else:
                        driver.back()
                except Exception:
                    pass
            get_bing_points(driver)
            if (i + 1) % 4 == 0:
                get_pc_search_progress(driver)
        except Exception as e:
            logger.warning(f"账号{email} 搜索 {word} 失败: {e}")
    driver.get(REWARDS_URL)
    time.sleep(3)
    get_bing_points(driver)
    logger.info(f"账号{email} 搜索任务完成。")

def logout_bing(driver):
    try:
        driver.get("https://login.live.com/logout.srf")
        time.sleep(2)
    except Exception:
        pass

def create_chrome_options():
    """
    创建Chrome选项
    """
    chrome_options = uc.ChromeOptions()
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--incognito')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--disable-plugins')
    chrome_options.add_argument('--disable-images')
    chrome_options.add_argument('--disable-web-security')
    chrome_options.add_argument('--allow-running-insecure-content')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    
    # 在GitHub Actions环境中添加额外选项
    if os.getenv('GITHUB_ACTIONS'):
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-software-rasterizer')
        chrome_options.add_argument('--disable-background-timer-throttling')
        chrome_options.add_argument('--disable-backgrounding-occluded-windows')
        chrome_options.add_argument('--disable-renderer-backgrounding')
        chrome_options.add_argument('--disable-features=TranslateUI')
        chrome_options.add_argument('--disable-ipc-flooding-protection')
        chrome_options.add_argument('--disable-setuid-sandbox')
        chrome_options.add_argument('--disable-accelerated-2d-canvas')
        chrome_options.add_argument('--disable-accelerated-jpeg-decoding')
        chrome_options.add_argument('--disable-accelerated-mjpeg-decode')
        chrome_options.add_argument('--disable-accelerated-video-decode')
        chrome_options.add_argument('--disable-gpu-sandbox')
        chrome_options.add_argument('--disable-software-rasterizer')
        chrome_options.add_argument('--disable-threaded-animation')
        chrome_options.add_argument('--disable-threaded-scrolling')
        chrome_options.add_argument('--disable-checker-imaging')
        chrome_options.add_argument('--disable-new-tab-first-run')
        chrome_options.add_argument('--disable-default-apps')
        chrome_options.add_argument('--disable-sync')
        chrome_options.add_argument('--disable-translate')
        chrome_options.add_argument('--disable-web-resources')
        chrome_options.add_argument('--disable-client-side-phishing-detection')
        chrome_options.add_argument('--disable-component-update')
        chrome_options.add_argument('--disable-domain-reliability')
        chrome_options.add_argument('--disable-features=VizDisplayCompositor')
        chrome_options.add_argument('--disable-hang-monitor')
        chrome_options.add_argument('--disable-prompt-on-repost')
        chrome_options.add_argument('--disable-renderer-backgrounding')
        chrome_options.add_argument('--disable-session-crashed-bubble')
        chrome_options.add_argument('--disable-single-click-autofill')
        chrome_options.add_argument('--disable-tab-for-desktop-share')
        chrome_options.add_argument('--disable-usb-keyboard-detect')
        chrome_options.add_argument('--disable-web-security')
        chrome_options.add_argument('--no-first-run')
        chrome_options.add_argument('--no-default-browser-check')
        chrome_options.add_argument('--no-zygote')
        chrome_options.add_argument('--single-process')
        chrome_options.add_argument('--disable-background-networking')
        chrome_options.add_argument('--disable-background-timer-throttling')
        chrome_options.add_argument('--disable-backgrounding-occluded-windows')
        chrome_options.add_argument('--disable-breakpad')
        chrome_options.add_argument('--disable-component-extensions-with-background-pages')
        chrome_options.add_argument('--disable-features=TranslateUI,BlinkGenPropertyTrees')
        chrome_options.add_argument('--disable-ipc-flooding-protection')
        chrome_options.add_argument('--disable-renderer-backgrounding')
        chrome_options.add_argument('--disable-sync-preferences')
        chrome_options.add_argument('--force-color-profile=srgb')
        chrome_options.add_argument('--metrics-recording-only')
        chrome_options.add_argument('--no-report-upload')
        chrome_options.add_argument('--disable-background-timer-throttling')
        chrome_options.add_argument('--disable-backgrounding-occluded-windows')
        chrome_options.add_argument('--disable-renderer-backgrounding')
    
    if HEADLESS:
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--remote-debugging-port=9222')
    
    return chrome_options

def process_account_group(group_name, accounts, search_words):
    """处理一个账号组（一个浏览器处理多个账号）"""
    logger.info(f"=== 开始处理账号组 {group_name} ===")
    
    driver = None
    try:
        logger.info(f"正在启动账号组 {group_name} 的Chrome浏览器...")
        logger.info("注意: 首次启动可能需要几分钟时间...")
        
        # 尝试多种方式启动Chrome
        driver = None
        for attempt in range(3):
            try:
                logger.info(f"账号组 {group_name} 第{attempt+1}次尝试启动Chrome...")
                logger.info("注意: 首次启动可能需要1-2分钟，请耐心等待...")
                
                # 使用线程来避免超时问题
                import threading
                
                driver_result = {'driver': None, 'error': None}
                
                def create_driver():
                    try:
                        # 为每个group创建新的Chrome选项，避免重用问题
                        chrome_options = create_chrome_options()
                        
                        # 为每个group使用不同的用户数据目录，避免冲突
                        import tempfile
                        import os
                        temp_dir = tempfile.mkdtemp(prefix=f"chrome_group_{group_name}_")
                        chrome_options.add_argument(f'--user-data-dir={temp_dir}')
                        chrome_options.add_argument(f'--remote-debugging-port={9222 + hash(group_name) % 1000}')
                        
                        driver_result['driver'] = uc.Chrome(options=chrome_options, version_main=138)
                        logger.info(f"账号组 {group_name} Chrome浏览器启动成功！")
                    except Exception as e:
                        logger.error(f"账号组 {group_name} ChromeDriver创建失败: {e}")
                        driver_result['error'] = e
                
                # 启动线程
                driver_thread = threading.Thread(target=create_driver)
                driver_thread.start()
                
                # 等待最多90秒
                driver_thread.join(timeout=90)
                
                if driver_thread.is_alive():
                    logger.warning(f"账号组 {group_name} 第{attempt+1}次启动超时（90秒），尝试重试...")
                    if attempt < 2:  # 不是最后一次尝试
                        logger.info("等待10秒后重试...")
                        time.sleep(10)
                    else:
                        raise Exception("Chrome启动超时，请检查网络连接或Chrome安装")
                else:
                    # 检查是否有错误
                    if driver_result['error']:
                        raise driver_result['error']
                    # 获取driver对象
                    driver = driver_result['driver']
                    if driver is None:
                        raise Exception("ChromeDriver创建失败，driver对象为空")
                    break  # 成功启动，跳出循环
                    
            except Exception as e:
                logger.warning(f"账号组 {group_name} 第{attempt+1}次启动失败: {e}")
                if attempt < 2:  # 不是最后一次尝试
                    logger.info("等待10秒后重试...")
                    time.sleep(10)
                else:
                    raise e
        
        # 处理该组中的所有账号
        for idx, account in enumerate(accounts):
            email = account['email']
            password = account['password']
            logger.info(f"\n==== 账号组 {group_name} 开始账号 {email} 的自动化任务 ====")
            
            try:
                # 检查driver是否还活着
                try:
                    driver.current_url
                except Exception:
                    logger.warning(f"账号组 {group_name} WebDriver连接已断开，尝试重新创建...")
                    try:
                        driver.quit()
                    except:
                        pass
                    
                    # 重新创建driver
                    for attempt in range(3):
                        try:
                            logger.info(f"账号组 {group_name} 第{attempt+1}次尝试重新启动Chrome...")
                            # 创建新的Chrome选项对象
                            new_chrome_options = create_chrome_options()
                            # 为重新创建的driver也使用独立的用户数据目录
                            import tempfile
                            temp_dir = tempfile.mkdtemp(prefix=f"chrome_group_{group_name}_retry_{attempt}_")
                            new_chrome_options.add_argument(f'--user-data-dir={temp_dir}')
                            new_chrome_options.add_argument(f'--remote-debugging-port={9222 + hash(group_name) % 1000 + attempt}')
                            
                            driver = uc.Chrome(options=new_chrome_options, version_main=138)
                            logger.info(f"账号组 {group_name} Chrome浏览器重新启动成功！")
                            break
                        except Exception as e:
                            logger.warning(f"账号组 {group_name} 第{attempt+1}次重新启动失败: {e}")
                            if attempt < 2:
                                time.sleep(10)
                            else:
                                raise Exception(f"无法重新启动Chrome: {e}")
                
                logger.info(f"开始登录账号 {email}...")
                login_bing(driver, email, password, idx, group_name)
                
                logger.info(f"开始签到奖励...")
                sign_in_rewards(driver, idx, email, group_name)
                
                logger.info(f"开始点击积分任务...")
                click_reward_tasks(driver, idx, email, group_name)
                
                logger.info(f"开始搜索赚积分...")
                search_for_points(driver, idx, email, search_words, group_name)
                
                logger.info(f"==== 账号组 {group_name} 账号 {email} 任务完成 ====")
                
            except Exception as e:
                logger.error(f"账号组 {group_name} 账号{email} 自动化流程异常: {e}")
                import traceback
                logger.error(f"详细错误信息: {traceback.format_exc()}")
                
                # 如果是WebDriver连接问题，尝试重新创建driver
                if "Failed to establish a new connection" in str(e) or "HTTPConnectionPool" in str(e) or "invalid session id" in str(e):
                    logger.warning(f"检测到WebDriver连接问题，尝试重新创建driver...")
                    try:
                        driver.quit()
                    except:
                        pass
                    driver = None
                    
                    # 重新创建driver
                    for attempt in range(3):
                        try:
                            logger.info(f"账号组 {group_name} 第{attempt+1}次尝试重新启动Chrome...")
                            # 创建新的Chrome选项对象
                            new_chrome_options = create_chrome_options()
                            # 为重新创建的driver也使用独立的用户数据目录
                            import tempfile
                            temp_dir = tempfile.mkdtemp(prefix=f"chrome_group_{group_name}_retry_{attempt}_")
                            new_chrome_options.add_argument(f'--user-data-dir={temp_dir}')
                            new_chrome_options.add_argument(f'--remote-debugging-port={9222 + hash(group_name) % 1000 + attempt}')
                            
                            driver = uc.Chrome(options=new_chrome_options, version_main=138)
                            logger.info(f"账号组 {group_name} Chrome浏览器重新启动成功！")
                            break
                        except Exception as e2:
                            logger.warning(f"账号组 {group_name} 第{attempt+1}次重新启动失败: {e2}")
                            if attempt < 2:
                                time.sleep(10)
                            else:
                                logger.error(f"无法重新启动Chrome，跳过剩余账号")
                                return  # 退出整个账号组处理
                
                continue  # 继续处理下一个账号
            
    except Exception as e:
        logger.error(f"账号组 {group_name} 整体异常: {e}")
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")
    finally:
        if driver:
            try:
                logger.info(f"正在关闭账号组 {group_name} 的浏览器...")
                logout_bing(driver)
                driver.quit()
                logger.info(f"账号组 {group_name} 浏览器已成功关闭")
            except Exception as e:
                logger.warning(f"关闭账号组 {group_name} 浏览器时出错: {e}")
        logger.info(f"=== 账号组 {group_name} 任务结束 ===")

def main():
    logger.info("=== 程序开始执行 ===")
    logger.info("正在读取账号配置文件...")
    with open('accounts.json', 'r', encoding='utf-8') as f:
        account_groups = json.load(f)
    
    total_accounts = sum(len(accounts) for accounts in account_groups.values())
    logger.info(f"成功读取到 {len(account_groups)} 个账号组，共 {total_accounts} 个账号")
    
    logger.info("正在获取搜索关键词...")
    search_words = get_bing_hotwords()
    logger.info(f"成功获取到 {len(search_words)} 个搜索关键词")
    
    # 使用多线程并行处理每个账号组
    import threading
    
    threads = []
    for i, (group_name, accounts) in enumerate(account_groups.items()):
        logger.info(f"创建账号组 {group_name} 的处理线程...")
        thread = threading.Thread(
            target=process_account_group, 
            args=(group_name, accounts, search_words)
        )
        threads.append(thread)
        thread.start()
        logger.info(f"账号组 {group_name} 线程已启动")
        
        # 增加延迟时间，避免同时启动时的资源竞争
        if i < len(account_groups) - 1:  # 不是最后一个group
            logger.info("等待15秒后启动下一个账号组，避免资源竞争...")
            time.sleep(15)
    
    # 等待所有线程完成
    logger.info("等待所有账号组任务完成...")
    for thread in threads:
        thread.join()
    
    logger.info("=== 所有账号组任务完成 ===")                 

def wait_until_2am():
    """等待到凌晨2点自动执行"""
    logger.info("=== 启动自动执行模式 ===")
    logger.info("程序将在每天凌晨2点自动执行")
    
    while True:
        try:
            now = datetime.datetime.now()
            next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
            
            # 如果当前时间已经过了今天的2点，则设置为明天的2点
            if now >= next_run:
                next_run += datetime.timedelta(days=1)
            
            wait_seconds = (next_run - now).total_seconds()
            hours = wait_seconds // 3600
            minutes = (wait_seconds % 3600) // 60
            
            logger.info(f"距离下次执行还有 {hours:.0f}小时{minutes:.0f}分钟")
            logger.info(f"下次执行时间: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 每小时输出一次状态
            if hours >= 1:
                time.sleep(3600)  # 睡1小时
            else:
                time.sleep(wait_seconds)  # 睡到执行时间
            
            logger.info("=== 开始执行定时任务 ===")
            main()
            logger.info("=== 定时任务执行完成 ===")
            
        except KeyboardInterrupt:
            logger.info("收到中断信号，退出自动执行模式")
            break
        except Exception as e:
            logger.error(f"自动执行过程中发生错误: {e}")
            logger.info("等待1小时后重试...")
            time.sleep(3600)

if __name__ == "__main__":
    import sys
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        if sys.argv[1] == "--once":
            # 只执行一次
            logger.info("=== 单次执行模式 ===")
            main()
        elif sys.argv[1] == "--auto":
            # 自动执行模式
            wait_until_2am()
        else:
            print("使用方法:")
            print("python bingZDH.py          # 执行一次")
            print("python bingZDH.py --once   # 执行一次")
            print("python bingZDH.py --auto   # 每天凌晨2点自动执行")
    else:
        # 默认执行一次
        main()
