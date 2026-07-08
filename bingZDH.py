import json
import time
import logging
import random
import re
import os
import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import requests
from bs4 import BeautifulSoup

# ========== CONFIG ==========
WAIT_TIMEOUT = 15000  # Playwright 用毫秒
BING_URL = "https://www.bing.com"
REWARDS_URL = "https://rewards.bing.com/"
LOG_FILE = "bing_automation.log"
HEADLESS = True
SLEEP_BETWEEN_SEARCH = (10, 30)
SLEEP_AFTER_4_SEARCH = 960
MAX_SKIP = 10
SEARCH_COUNT = 35

if os.getenv('GITHUB_ACTIONS'):
    HEADLESS = True
    WAIT_TIMEOUT = 20000
    SLEEP_BETWEEN_SEARCH = (5, 12)
    SLEEP_AFTER_4_SEARCH = 60
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

# ========== 热搜关键词 ==========
def get_bing_hotwords():
    logger.info("开始获取热搜关键词...")
    try:
        resp = requests.get("https://top.baidu.com/board?tab=realtime", timeout=8,
                            proxies={"http": None, "https": None})
        soup = BeautifulSoup(resp.text, "html.parser")
        hotwords = [tag.text.strip() for tag in soup.select(".c-single-text-ellipsis")]
        if hotwords:
            logger.info(f"已获取百度热搜词：{hotwords[:40]}")
            return hotwords[:40]
    except Exception as e:
        logger.warning(f"获取百度热搜失败：{e}")
    try:
        resp = requests.get("https://s.weibo.com/top/summary", timeout=8,
                            proxies={"http": None, "https": None})
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
        "股票", "电影", "电视剧", "旅游", "健康", "教育", "汽车", "手机", "数码", "美食",
        "历史", "地理", "音乐", "游戏", "动漫"
    ]

# ========== State 持久化 ==========
def get_state_filename(email):
    safe = email.replace('@', '_at_').replace('.', '_')
    return f"state_{safe}.json"

def save_state(context, email):
    try:
        context.storage_state(path=get_state_filename(email))
        logger.info(f"已保存登录状态到 {get_state_filename(email)}")
    except Exception as e:
        logger.warning(f"保存登录状态失败: {e}")

def try_state_login(browser, email):
    state_file = get_state_filename(email)
    if not os.path.exists(state_file):
        logger.info(f"未找到状态文件: {state_file}")
        return None
    try:
        context = browser.new_context(
            storage_state=state_file,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        apply_stealth(context)
        page = context.new_page()
        page.goto(REWARDS_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
        time.sleep(3)
        if "login.live.com" not in page.url and "login.microsoftonline.com" not in page.url:
            logger.info("状态登录成功！")
            return context
        logger.info("状态已过期，需要重新登录")
        context.close()
        return None
    except Exception as e:
        logger.warning(f"加载状态失败: {e}")
        try:
            context.close()
        except Exception:
            pass
        return None

# ========== 浏览器设置 ==========
def apply_stealth(context):
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        window.chrome = { runtime: {} };
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
    """)

def create_browser(playwright):
    # 优先使用系统 Chrome（避免下载 Playwright 自带 Chromium）
    try:
        return playwright.chromium.launch(
            channel="chrome",
            headless=HEADLESS,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--disable-extensions',
                '--disable-plugins',
            ]
        )
    except Exception:
        return playwright.chromium.launch(
            headless=HEADLESS,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--disable-extensions',
                '--disable-plugins',
            ]
        )

def create_context(browser):
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
    )
    apply_stealth(context)
    return context

# ========== 登录 ==========
def login_bing(page, email, password):
    logger.info(f"开始登录账号 {email}...")
    page.goto(BING_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
    time.sleep(2)

    # 点击登录按钮
    login_clicked = False
    for selector in ["#id_l", "a.id_button"]:
        try:
            page.locator(selector).first.click(timeout=5000)
            login_clicked = True
            logger.info(f"点击登录按钮成功: {selector}")
            break
        except Exception:
            continue
    if not login_clicked:
        for pattern in [re.compile("登录|Sign in|登入")]:
            try:
                page.get_by_role("link", name=pattern).first.click(timeout=5000)
                login_clicked = True
                logger.info("点击登录按钮成功 (role)")
                break
            except Exception:
                continue
    if not login_clicked:
        raise Exception("未找到登录按钮")

    time.sleep(3)

    # 输入邮箱
    email_entered = False
    for selector in ["input[name='loginfmt']", "#usernameEntry", "#i0116", "input[type='email']"]:
        try:
            page.locator(selector).first.fill(email, timeout=10000)
            email_entered = True
            logger.info("输入邮箱成功")
            break
        except Exception:
            continue
    if not email_entered:
        raise Exception("未找到邮箱输入框")

    # 点击 Next
    try:
        page.locator("button[data-testid='primaryButton']").click(timeout=WAIT_TIMEOUT)
    except Exception:
        page.get_by_role("button", name=re.compile("Next|下一个|下一步")).first.click(timeout=WAIT_TIMEOUT)

    # 等待页面加载
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    time.sleep(2)

    # 处理登录方式选择页面（新版直接到 "Sign in another way"，旧版先到 Authenticator）
    page_text = page.content()

    if "Sign in another way" in page_text:
        # 新版流程：直接在"Sign in another way"页面
        logger.info("检测到'Sign in another way'页面，点击'Use your password'...")
        try:
            page.get_by_text("Use your password").click(timeout=5000)
            time.sleep(2)
        except Exception as e:
            logger.warning(f"点击'Use your password'失败: {e}")
    elif "Authenticator" in page_text:
        # 旧版流程：先在Authenticator页面，需点击"Other ways"
        logger.info("检测到Authenticator页面，切换到密码登录...")
        try:
            page.get_by_text("Other ways to sign in").click(timeout=5000)
            time.sleep(2)
            page.get_by_text("Use your password").click(timeout=5000)
            time.sleep(2)
        except Exception as e:
            logger.warning(f"切换密码登录失败: {e}")

    if any(x in page_text for x in ["获取用于登录的代码", "Send code", "We'll send a code"]):
        logger.info("检测到验证码页面，切换到密码登录...")
        try:
            page.get_by_text(re.compile("使用密码|Use your password|Use password")).first.click(timeout=5000)
            time.sleep(2)
        except Exception as e:
            logger.warning(f"切换密码登录失败: {e}")

    # 等待并输入密码
    password_input = None
    for selector in ["input[name='passwd']", "#passwordEntry", "#i0118"]:
        try:
            el = page.locator(selector).first
            el.wait_for(state="visible", timeout=WAIT_TIMEOUT)
            password_input = el
            break
        except Exception:
            continue
    if not password_input:
        raise Exception("未找到密码输入框")

    password_input.fill(password)
    logger.info("输入密码成功")

    # 点击登录
    try:
        page.locator("button[data-testid='primaryButton']").click(timeout=WAIT_TIMEOUT)
    except Exception:
        page.get_by_role("button", name=re.compile("登录|Sign in|下一个|Next")).first.click(timeout=WAIT_TIMEOUT)

    logger.info("已提交密码，等待响应...")

    # 处理登录后页面
    handle_post_login(page, email)

def handle_post_login(page, email):
    """处理登录后的弹窗和跳转"""
    for _ in range(MAX_SKIP):
        time.sleep(2)
        url = page.url

        # 已到 Bing
        if "bing.com" in url and "login" not in url and "setup" not in url and "create" not in url:
            logger.info(f"账号 {email} 登录成功！")
            return True

        # 检测 2FA 验证码页面（无法自动处理）
        try:
            title = page.title()
            if "Enter the code" in title or "输入代码" in title or "输入验证码" in title:
                logger.error(f"账号 {email} 需要输入2FA验证码，自动化无法处理。请先运行 --manual 模式手动登录。")
                return False
        except Exception:
            pass

        # "Stay signed in" 弹窗 - 用 role 定位
        try:
            yes_btn = page.get_by_role("button", name=re.compile("Yes|是", re.I))
            if yes_btn.count() > 0 and yes_btn.first.is_visible():
                yes_btn.first.click(timeout=5000)
                logger.info("点击'Yes/是'按钮")
                time.sleep(3)
                continue
        except Exception:
            pass

        # 也尝试 input[value] 形式
        try:
            for val in ["Yes", "是"]:
                inp = page.locator(f"input[value='{val}']")
                if inp.count() > 0 and inp.first.is_visible():
                    inp.first.click(timeout=3000)
                    logger.info(f"点击 input[value='{val}']")
                    time.sleep(3)
                    break
        except Exception:
            pass

        # 通行密钥页面 - 跳过
        try:
            skip = page.get_by_text(re.compile("暂时跳过|Skip for now|Not now", re.I))
            if skip.count() > 0 and skip.first.is_visible():
                skip.first.click(timeout=3000)
                logger.info("点击'暂时跳过'")
                time.sleep(2)
                continue
        except Exception:
            pass

        # setup/create 页面 - 强制跳转
        if "setup" in url or "create" in url:
            page.goto(BING_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
            time.sleep(2)
            continue

    if "bing.com" in page.url and "login" not in page.url:
        logger.info(f"账号 {email} 登录成功！")
        return True
    logger.warning(f"账号 {email} 登录流程完成，当前: {page.url}")
    return False

# ========== Rewards 操作 ==========
def get_bing_points(page):
    """获取积分信息（从页面文本提取，不依赖 JSON 嵌入）"""
    page.goto(REWARDS_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
    time.sleep(5)

    total_points = "未找到"
    today_points = "未找到"

    try:
        content = page.inner_text("body")
        m = re.search(r'可用积分\s*[\n\r\s]*([\d,]+)', content)
        if m:
            total_points = m.group(1)
        m = re.search(r'今日积分\s*[\n\r\s]*([\d,]+)', content)
        if m:
            today_points = m.group(1)
    except Exception as e:
        logger.warning(f"获取积分失败: {e}")

    logger.info(f"当前Bing总积分：{total_points}，今日积分：{today_points}")
    return total_points, today_points

def claim_expiring_points(page, email):
    """领取即将过期的积分"""
    try:
        btn = page.get_by_role("button", name="领取")
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click(timeout=5000)
            logger.info(f"账号{email} 已领取过期积分")
            time.sleep(2)
    except Exception:
        pass

def click_reward_tasks(page, context, email):
    """点击积分任务卡片（新版 Rewards 页面）"""
    logger.info(f"账号{email} 开始点击积分任务...")
    page.goto(REWARDS_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
    time.sleep(5)

    tasks = page.evaluate("""() => {
        const links = Array.from(document.querySelectorAll('a[href]'));
        const seen = new Set();
        const results = [];
        for (const a of links) {
            const href = a.href;
            if (!href || seen.has(href) || !href.startsWith('http')) continue;
            // 排除 Bing 首页链接（在必应上浏览任务的通用 URL）
            if (href.match(/bing\\.com\\/\\?(form|OCID|PUBL)/) || href === 'https://www.bing.com/') continue;
            // 包含搜索链接（带 form 参数 = 积分任务）
            if (href.includes('bing.com/search') && (href.includes('form=') || href.includes('FORM='))) {
                seen.add(href);
                results.push({ href, label: (a.getAttribute('aria-label') || '').substring(0, 60) });
            }
            // 包含测验/投票链接
            else if (href.includes('bing.com/rewards/checkuser')) {
                seen.add(href);
                results.push({ href, label: (a.getAttribute('aria-label') || '').substring(0, 60) });
            }
        }
        return results;
    }""")

    logger.info(f"账号{email} 找到 {len(tasks)} 个积分任务")

    for i, task in enumerate(tasks):
        try:
            tp = context.new_page()
            tp.goto(task['href'], wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
            time.sleep(8)
            tp.close()
            logger.info(f"账号{email} 完成第 {i+1}/{len(tasks)} 个任务: {task['label'][:30]}")
        except Exception as e:
            logger.warning(f"账号{email} 第 {i+1} 个任务失败: {e}")
            try:
                tp.close()
            except Exception:
                pass

def search_for_points(page, email, search_words):
    """搜索赚积分"""
    logger.info(f"账号{email} 开始搜索赚积分...")

    words = search_words[:SEARCH_COUNT]
    for i, word in enumerate(words):
        try:
            delay = random.randint(*SLEEP_BETWEEN_SEARCH)
            logger.info(f"等待 {delay} 秒后进行第 {i+1}/{len(words)} 次搜索...")
            time.sleep(delay)

            if (i + 1) % 5 == 0 and i > 0:
                logger.info(f"暂停 {SLEEP_AFTER_4_SEARCH} 秒...")
                time.sleep(SLEEP_AFTER_4_SEARCH)

            page.goto(BING_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)

            search_box = page.locator('#sb_form_q, textarea[name="q"], input[name="q"]').first
            search_box.wait_for(state="visible", timeout=10000)
            search_box.fill(word)
            page.keyboard.press("Enter")

            page.wait_for_load_state("domcontentloaded", timeout=WAIT_TIMEOUT)
            logger.info(f"账号{email} 搜索：{word}")

            # 偶尔点击搜索结果模拟人类行为
            if random.random() < 0.3:
                try:
                    first = page.locator('li.b_algo h2 a, .b_algo h2 a').first
                    if first.is_visible():
                        first.click(timeout=5000)
                        time.sleep(random.uniform(3, 7))
                        if len(page.context.pages) > 1:
                            page.context.pages[-1].close()
                        page.go_back(wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
                except Exception:
                    pass

            # 每4次搜索获取积分
            if (i + 1) % 4 == 0:
                get_bing_points(page)

        except Exception as e:
            logger.warning(f"账号{email} 搜索 {word} 失败: {e}")

    get_bing_points(page)
    logger.info(f"账号{email} 搜索任务完成。")

# ========== 主流程 ==========
def process_account_group(group_name, accounts, search_words):
    """处理一个账号组（一个浏览器处理多个账号）"""
    logger.info(f"=== 开始处理账号组 {group_name} ===")

    with sync_playwright() as p:
        browser = create_browser(p)

        for account in accounts:
            email = account['email']
            password = account['password']
            logger.info(f"\n==== 账号组 {group_name} 开始账号 {email} 的自动化任务 ====")

            context = None
            try:
                # 尝试状态登录
                context = try_state_login(browser, email)

                if context:
                    page = context.pages[0] if context.pages else context.new_page()
                    logger.info(f"账号{email} 使用已保存状态登录")
                else:
                    # 全新登录
                    context = create_context(browser)
                    page = context.new_page()
                    login_bing(page, email, password)
                    save_state(context, email)

                # 访问 Rewards 页面
                page.goto(REWARDS_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
                time.sleep(3)

                # 获取积分
                get_bing_points(page)

                # 领取过期积分
                claim_expiring_points(page, email)

                # 点击积分任务
                click_reward_tasks(page, context, email)

                # 搜索赚积分
                search_for_points(page, email, search_words)

                # 最终积分
                get_bing_points(page)

                # 保存状态
                save_state(context, email)

                logger.info(f"==== 账号组 {group_name} 账号 {email} 任务完成 ====")

            except Exception as e:
                logger.error(f"账号 {email} 自动化流程异常: {e}")
                import traceback
                logger.error(f"详细错误: {traceback.format_exc()}")

                # 截图
                if context:
                    try:
                        for pg in context.pages:
                            ts = int(time.time())
                            safe_email = re.sub(r'[^a-zA-Z0-9_]', '_', email)
                            pg.screenshot(path=f"error_{safe_email}_{ts}.png")
                    except Exception:
                        pass

            finally:
                if context:
                    try:
                        context.close()
                    except Exception:
                        pass

        browser.close()

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

        if i < len(account_groups) - 1:
            logger.info("等待15秒后启动下一个账号组...")
            time.sleep(15)

    logger.info("等待所有账号组任务完成...")
    for thread in threads:
        thread.join()

    logger.info("=== 所有账号组任务完成 ===")

def wait_until_2am():
    logger.info("=== 启动自动执行模式 ===")
    logger.info("程序将在每天凌晨2点自动执行")

    while True:
        try:
            now = datetime.datetime.now()
            next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)

            if now >= next_run:
                next_run += datetime.timedelta(days=1)

            wait_seconds = (next_run - now).total_seconds()
            hours = wait_seconds // 3600
            minutes = (wait_seconds % 3600) // 60

            logger.info(f"距离下次执行还有 {hours:.0f}小时{minutes:.0f}分钟")
            logger.info(f"下次执行时间: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

            if hours >= 1:
                time.sleep(3600)
            else:
                time.sleep(wait_seconds)

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

def manual_login():
    """手动登录模式：打开可见浏览器，用户自行完成登录（含2FA），登录后保存状态"""
    logger.info("=== 手动登录模式 ===")
    logger.info("将打开浏览器，请手动完成登录（包括2FA验证码）。")
    logger.info("登录成功后脚本会自动保存状态。")

    with open('accounts.json', 'r', encoding='utf-8') as f:
        account_groups = json.load(f)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome" if os.path.exists("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe") else None,
            headless=False,  # 可见模式
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled']
        )

        for group_name, accounts in account_groups.items():
            for account in accounts:
                email = account['email']
                logger.info(f"\n=== 请登录账号: {email} ===")

                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 900},
                    locale="en-US",
                )
                apply_stealth(context)
                page = context.new_page()
                page.goto(BING_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)

                # 等待用户手动登录，最多等10分钟
                logger.info("等待登录完成（最多10分钟）...")
                for i in range(600):  # 10分钟 = 600秒
                    time.sleep(1)
                    try:
                        url = page.url
                        if "bing.com" in url and "login" not in url and "rewards" not in url:
                            # 确认是真正的 bing.com 主页
                            if page.title() and "bing" in page.title().lower():
                                logger.info(f"检测到登录成功！保存状态...")
                                save_state(context, email)
                                break
                    except Exception:
                        pass
                else:
                    logger.warning(f"账号 {email} 等待超时，未检测到登录成功")

                # 额外等待3秒确保页面稳定
                time.sleep(3)
                try:
                    save_state(context, email)
                except Exception:
                    pass
                context.close()

        browser.close()
    logger.info("=== 手动登录完成 ===")

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "--once":
            logger.info("=== 单次执行模式 ===")
            main()
        elif sys.argv[1] == "--auto":
            wait_until_2am()
        elif sys.argv[1] == "--manual":
            manual_login()
        else:
            print("使用方法:")
            print("python bingZDH.py            # 执行一次（自动模式）")
            print("python bingZDH.py --once     # 执行一次（自动模式）")
            print("python bingZDH.py --auto     # 每天凌晨2点自动执行")
            print("python bingZDH.py --manual   # 手动登录模式（打开浏览器，用于首次登录或2FA）")
    else:
        main()
