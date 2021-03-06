# coding: utf-8

import sys
import platform
import os

if __name__ == "__main__":
    sys.path.append('..')
import time
import logging
import datetime
from selenium.common import exceptions as SeleniumExceptions
from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from db.dbBasic import mongo_cli
from EasyGoSpider import settings
from PIL import Image
from EasyGoSpider.yundama import get_captcha_res

reload(sys)
sys.setdefaultencoding('utf-8')

if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p')
    logger = logging.getLogger('cookie')
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
else:
    logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------------------------------------------------

TODAY = str(datetime.date.today())
ACCOUNT_FAIL_UPPER_LIMIT = settings.MAX_FAIL_TIME
LoginURL = 'http://ui.ptlogin2.qq.com/cgi-bin/login?' \
           'appid=1600000601&style=9&s_url=http%3A%2F%2Fc.easygo.qq.com%2Feg_toc%2Fmap.html'
# ---------------------------------------------------------------------------------------------------------------------

dcap = dict(DesiredCapabilities.PHANTOMJS)
dcap["phantomjs.page.settings.userAgent"] = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36"
)


def update_time(item):
    item.update({'update_time': time.time()})


def init_cookies(myAccount):
    """    获取Cookies
    仅限新增账号初始化
    """
    for idx, elem in enumerate(myAccount):
        if list(mongo_cli.cookies.find({"account": elem})):
            continue
        res = {}
        cookie = get_cookie_for_one_account(elem)
        res['account'] = elem
        res['cookie'] = cookie
        if cookie:
            logger.info(idx, elem, "init cookies done")
            update_time(res)
        mongo_cli.cookies.insert(res)


def get_cookie_for_one_account(elem):
    account = elem['no']
    password = elem['psw']
    logger.info("Fetching cookie for %s" % account)
    for i in range(3):
        logger.info("Trying %s time%s..." % (i + 1, "s" if i else ''))
        try:
            browser = webdriver.PhantomJS(desired_capabilities=dcap)
            browser.get(LoginURL)
            time.sleep(3)

            username = browser.find_element_by_id("u")
            username.clear()
            username.send_keys(account)
            psd = browser.find_element_by_id("p")
            psd.clear()
            psd.send_keys(password)
            commit = browser.find_element_by_id("go")
            commit.click()
            time.sleep(5)

            if "宜出行" in browser.title:
                return after_smoothly_login(browser)
            elif "手机统一登录" in browser.title:
                browser.switch_to.frame(browser.find_element_by_xpath(r'//*[@id="new_vcode"]/iframe[2]'))
                time.sleep(2)
                img_path = './verify_code.png'
                save_verify_img = browser.find_element_by_xpath(r'//*[@id="cap_que_img"]').screenshot(img_path)
                with Image.open(img_path) as f:
                    x, y = 65, 89
                    w, h = 132, 53
                    f.crop((x, y, x + w, y + h)).save(img_path)
                if save_verify_img:
                    verify_res = recogniz_vcode(img_path)
                    logger.info('Got vcode: %s' % verify_res)
                    verify_aera = browser.find_element_by_xpath(r'//*[@id="cap_input"]')  # 65, 89, 132, 53
                    verify_aera.clear()
                    verify_aera.send_keys(verify_res)
                    browser.find_element_by_xpath(r'//span[@id="verify_btn"]').click()
                    time.sleep(3)
                    if "宜出行" in browser.title:
                        return after_smoothly_login(browser)
                    else:
                        mongo_cli.cookies.find_one_and_update({"account": elem}, {"$inc": {"AuthFailed": 1}})
        except SeleniumExceptions.NoSuchElementException, e:
            logger.exception(e)
        except Exception, e:
            logger.exception(e)
        finally:
            try:
                browser.quit()
            except Exception, e:
                logger.debug(e)
            if settings.AUTO_CLEAR_PHANTOMJS and platform.system() == 'Linux':
                os.system("sh ./EasyGoSpider/killbyname.sh phantomjs")
            time.sleep(3)
    logger.warning("Get Cookie Failed: %s!" % account)
    return {}


def recogniz_vcode(img_path):
    """     识别验证码
    """
    if settings.CAPTCHA_RECOGNIZ == 1:  # manually recognize captcha
        logger.info("请找到 %s " % img_path)
        return raw_input("手动在此处输入验证码：\n")
    elif settings.CAPTCHA_RECOGNIZ == 2:  # auto via yundama
        return get_captcha_res(img_path)


def after_smoothly_login(browser):
    """     成功登录之后
    """
    cookie = {}
    for elem in browser.get_cookies():
        cookie[elem["name"]] = elem["value"]
    if len(cookie) > 0:
        logger.info("...got a new cookie")
        return cookie


def fetch_cookies(ignored_cookies):
    """    fetch existed cookies from mongo
    """
    if settings.REFRESH_COOKIES:
        for dct in mongo_cli.cookies.find({}):
            try:
                assert dct.get('FailedDate') != TODAY, "BANNED today: %s" % dct  # 今日访问次数过多
                assert dct.get("AuthFailed") < ACCOUNT_FAIL_UPPER_LIMIT, "Beyond failure limitation: %s" % dct  # 可能被禁
                assert dct.get("cookie") not in ignored_cookies
                assert dct.get("update_time") is None or time.time() - dct.get(
                    "update_time") > settings.COOKIE_INTERVAL, "update_time mismatchs conditions: %s" % dct
                refresh_cookie(dct)
            except AssertionError, e:
                logger.debug(e)
    return [i['cookie'] for i in mongo_cli.cookies.find({})
            if i['cookie']
            and (i.get('FailedDate') != TODAY)
            and (i.get("AuthFailed") < ACCOUNT_FAIL_UPPER_LIMIT)]


def refresh_cookie(dct):
    """    update cookie which is no longer available
    """
    new_cookie = get_cookie_for_one_account(dct.get('account'))
    update_part = {'cookie': new_cookie}
    if new_cookie:
        update_time(update_part)
    mongo_cli.cookies.find_one_and_update({'_id': dct['_id']},
                                          {'$set': update_part})


def try_to_get_enough_cookies():
    logger.info("...start fetching COOKIES.")
    cookies = []
    for i in range(3):
        cookies = fetch_cookies(cookies)
        if len(cookies) < 3:
            logger.info("Find %s. Not enough. Trying again..." % len(cookies))
        else:
            break
    logger.info("Got %s cookies." % len(cookies))
    return cookies


if __name__ == '__main__':
    # try_to_get_enough_cookies(1)
    myAccount = []
    for line in ''''''.split():
        no, psw = line.split('----')
        myAccount.append({'no': no, 'psw': psw})
    print myAccount.__repr__()
    init_cookies(myAccount)
