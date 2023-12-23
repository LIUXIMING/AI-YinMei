# b站AI直播对接本地语言模型
import datetime
import queue
import subprocess
import threading
import os
import time

from peft import PeftModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bilibili_api import live, sync, Credential
from transformers import AutoTokenizer, AutoModel, AutoConfig
from pynput.keyboard import Key, Controller
from duckduckgo_search import DDGS

print("=====================================================================")
print("开始启动人工智能吟美！")
print("当前AI使用最新ChatGLM3引擎开发")
print("ChatGLM3-6B：https://github.com/THUDM/ChatGLM3-6B")
print("开发作者 by Winlone")
print("=====================================================================\n")

os.environ["CUDA_LAUNCH_BLOCKING"] = "1"
QuestionList = queue.Queue(10)  # 定义问题 用户名 回复 播放列表 四个先进先出队列
QuestionName = queue.Queue(10)
AnswerList = queue.Queue()
MpvList = queue.Queue()
EmoteList = queue.Queue()
LogsList = queue.Queue()
history = []
is_ai_ready = True  # 定义ai回复是否转换完成标志
is_tts_ready = True  # 定义语音是否生成完成标志
is_mpv_ready = True  # 定义是否播放完成标志
AudioCount = 0
enable_history = False  # 是否启用记忆
history_count = 2  # 定义最大对话记忆轮数,请注意这个数值不包括扮演设置消耗的轮数，只有当enable_history为True时生效
enable_role = False  # 是否启用扮演模式
# b站直播身份验证：实例化 Credential 类
cred = Credential(
    sessdata="cYNHO_RqXl9EuDWwz-_vWYmI6hDhvO3q_kSVmtRREcwS3I2aW9VRVlOamhJcEVTTUtfT0paR2pnNHVSYjZCS09meUlqTzVwVFltT1V2OXRmdHNsNmZjMHNweEszdnNGYTR0ZHBwVjlEaGtveGg1czF3IIEC",
    buvid3="",
)

# AI基础模型路径
model_path = "ChatGLM2/THUDM/chatglm2-6b"
# 训练模型路径
ptuning_path = "ChatGLM2/ptuning/lora2/mydo-pt-128-0.0018/checkpoint-1000"


# 初始化设定
def initialize():
    global enable_history  # 是否启用记忆
    global history_count  # 定义最大对话记忆轮数,请注意这个数值不包括扮演设置消耗的轮数，只有当enable_history为True时生效
    global enable_role  # 是否启用扮演模式

    print(f"\n扮演模式启动状态为：{enable_role}")
    if enable_history:
        print(f"会话记忆启动状态为：{enable_history}")
        print(f"会话记忆轮数为：{history_count}\n")
    else:
        print(f"会话记忆启动状态为：{enable_history}\n")


# 读取扮演设置
def role_set():
    global history
    print("\n开始初始化扮演设定")
    print("请注意：此时会读取并写入Role_setting.txt里的设定，行数越多占用的对话轮数就越多，请根据配置酌情设定\n")
    with open("Role_setting.txt", "r", encoding="utf-8") as f:
        role_setting = f.readlines()
    for setting in role_setting:
        role_response, history = model.chat(tokenizer, setting.strip(), history=history)
        print(f"\033[32m[设定]\033[0m：{setting.strip()}")
        print(f"\033[31m[回复]\033[0m：{role_response}\n")
    return history


initialize()
print("=====================================================================\n")
print(f"开始导入ChatGLM模型\n")

tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
# 导入chatglm 你可以换你喜欢的版本模型. 量化int8： .quantize(8)
model = AutoModel.from_pretrained(model_path, trust_remote_code=True).cuda()


# lora加载训练模型
model = PeftModel.from_pretrained(
    model,
    "LLaMA-Factory/saves/ChatGLM2-6B-Chat/lora/yinmei-20231123-ok-last",
)
model = model.merge_and_unload()

model = model.eval()
if enable_role:
    print("\n=====================================================================")
    Role_history = role_set()
else:
    Role_history = []

print("--------------------")
print("启动成功！")
print("--------------------")

room_id = int(input("输入你的直播间编号: "))  # 输入直播间编号
room = live.LiveDanmaku(room_id, credential=cred)  # 连接弹幕服务器
sched1 = AsyncIOScheduler(timezone="Asia/Shanghai")


@room.on("INTERACT_WORD")  # 用户进入直播间
async def in_liveroom(event):
    global is_ai_ready
    user_name = event["data"]["data"]["uname"]  # 获取用户昵称
    time1 = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{time1}:粉丝\033[36m[{user_name}]\033[0m进入了直播间")
    # 直接放到语音合成处理
    AnswerList.put(f"欢迎{user_name}来到吟美的直播间")


@room.on("DANMU_MSG")  # 弹幕消息事件回调函数
async def input_msg(event):
    """
    处理弹幕消息
    """
    global QuestionList
    global QuestionName
    global LogsList
    content = event["data"]["info"][1]  # 获取弹幕内容
    user_name = event["data"]["info"][2][1]  # 获取用户昵称
    print(f"\033[36m[{user_name}]\033[0m:{content}")  # 打印弹幕信息
    if not QuestionList.full():
        QuestionName.put(user_name)  # 将用户名放入队列
        QuestionList.put(content)  # 将弹幕消息放入队列
        time1 = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        LogsList.put(f"[{time1}] [{user_name}]：{content}")
        print("\033[32mSystem>>\033[0m已将该条弹幕添加入问题队列")
    else:
        print("\033[32mSystem>>\033[0m队列已满，该条弹幕被丢弃")


def ai_response():
    """
    从问题队列中提取一条，生成回复并存入回复队列中
    :return:
    """
    global is_ai_ready
    global QuestionList
    global AnswerList
    global QuestionName
    global LogsList
    global history
    prompt = QuestionList.get()
    user_name = QuestionName.get()
    ques = LogsList.get()

    # 搜索引擎查询
    text = ["查询", "查一下", "搜索"]
    num = is_index_contain_string(text, prompt)
    query = prompt[num : len(prompt)]
    print("搜索词：" + query)
    searchStr = ""
    if num > 0:
        searchStr = web_search(query)
    if searchStr != "":
        prompt = f'帮我在答案"{searchStr}"中提取"{query}"的信息'
        print(f"重置提问:{prompt}")
    # 询问LLM
    if (
        len(history) >= len(Role_history) + history_count and enable_history
    ):  # 如果启用记忆且达到最大记忆长度
        history = Role_history + history[-history_count:]
        response, history = model.chat(tokenizer, prompt, history=history)
        # response, history = chat_response(prompt,history,None,True)
    elif enable_role and not enable_history:  # 如果没有启用记忆且启用扮演
        history = Role_history
        response, history = model.chat(tokenizer, prompt, history=history)
        # response, history = chat_response(prompt,[],None,True)
    elif enable_history:  # 如果启用记忆
        response, history = model.chat(tokenizer, prompt, history=history)
        # response, history = chat_response(prompt,history,None,True)
    elif not enable_history:  # 如果没有启用记忆
        response, history = model.chat(tokenizer, prompt, history=[])
        # response, history = chat_response(prompt,[],None,True)
    else:
        response = ["Error：记忆和扮演配置错误！请检查相关设置"]
        print(response)
    answer = f"回复{user_name}：{response}"
    # 加入回复列表，并且后续合成语音
    AnswerList.put(f"{prompt}" + "," + answer)
    current_question_count = QuestionList.qsize()
    print(f"\033[31m[ChatGLM]\033[0m{answer}")  # 打印AI回复信息
    print(
        f"\033[32mSystem>>\033[0m[{user_name}]的回复已存入队列，当前剩余问题数:{current_question_count}"
    )
    time2 = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("./logs.txt", "a", encoding="utf-8") as f:  # 将问答写入logs
        f.write(
            f"{ques}\n[{time2}] {answer}\n========================================================\n"
        )
    is_ai_ready = True  # 指示AI已经准备好回复下一个问题


def web_search(query):
    content = ""
    with DDGS(proxies="socks5://localhost:10806", timeout=20) as ddgs:
        for r in ddgs.text(
            query,
            region="cn-zh",
            timelimit="d",
            backend="api",
            max_results=2,
        ):
            print("搜索内容：" + r["body"])
            content = content + r["body"]
    return content


def check_answer():
    """
    如果AI没有在生成回复且队列中还有问题 则创建一个生成的线程
    :return:
    """
    global is_ai_ready
    global QuestionList
    global AnswerList
    if not QuestionList.empty() and is_ai_ready:
        is_ai_ready = False
        answers_thread = threading.Thread(target=ai_response())
        answers_thread.start()


def check_tts():
    """
    如果语音已经放完且队列中还有回复 则创建一个生成并播放TTS的线程
    :return:
    """
    global is_tts_ready
    if not AnswerList.empty() and is_tts_ready:
        is_tts_ready = False
        tts_thread = threading.Thread(target=tts_generate())
        tts_thread.start()


def tts_generate():
    """
    从回复队列中提取一条，通过edge-tts生成语音对应AudioCount编号语音
    :return:
    """
    global is_tts_ready
    global AnswerList
    global MpvList
    global AudioCount
    response = AnswerList.get()
    with open("./output/output.txt", "w", encoding="utf-8") as f:
        f.write(f"{response}")  # 将要读的回复写入临时文件
    subprocess.run(
        f"edge-tts --voice zh-CN-XiaoyiNeural --f .\output\output.txt --write-media .\output\output{AudioCount}.mp3 2>nul",
        shell=True,
    )  # 执行命令行指令
    begin_name = response.find("回复")
    end_name = response.find("：")
    contain = response.find("来到吟美的直播")
    if contain > 0:
        # 欢迎语
        print(
            f"\033[32mSystem>>\033[0m对[{response}]的回复已成功转换为语音并缓存为output{AudioCount}.mp3"
        )
        # 表情加入:使用键盘控制VTube
        EmoteList.put(f"{response}")
    else:
        # 回复语
        name = response[begin_name + 2 : end_name]
        print(f"\033[32mSystem>>\033[0m对[{name}]的回复已成功转换为语音并缓存为output{AudioCount}.mp3")
        # 表情加入:使用键盘控制VTube
        emote = response[end_name : len(response)]
        EmoteList.put(f"{emote}")
    # 加入音频播放列表
    MpvList.put(AudioCount)
    AudioCount += 1
    is_tts_ready = True  # 指示TTS已经准备好回复下一个问题


def emote_show(response):
    # 表情加入:使用键盘控制VTube
    keyboard = Controller()
    # =========== 开心 ==============
    text = ["笑", "不错", "哈", "开心", "呵", "嘻"]
    emote_thread1 = threading.Thread(
        target=emote_do(text, response, keyboard, 0.2, Key.f1)
    )
    emote_thread1.start()
    # =========== 招呼 ==============
    text = ["你好", "在吗", "干嘛", "名字", "欢迎"]
    emote_thread2 = threading.Thread(
        target=emote_do(text, response, keyboard, 0.2, Key.f2)
    )
    emote_thread2.start()
    # =========== 生气 ==============
    text = ["生气", "不理你", "骂", "臭", "打死", "可恶", "白痴", "忘记"]
    emote_thread3 = threading.Thread(
        target=emote_do(text, response, keyboard, 0.2, Key.f3)
    )
    emote_thread3.start()
    # =========== 尴尬 ==============
    text = ["尴尬", "无聊", "无奈", "傻子", "郁闷", "龟蛋"]
    emote_thread4 = threading.Thread(
        target=emote_do(text, response, keyboard, 0.2, Key.f4)
    )
    emote_thread4.start()
    # =========== 认同 ==============
    text = ["认同", "点头", "嗯", "哦", "女仆"]
    emote_thread5 = threading.Thread(
        target=emote_do(text, response, keyboard, 0.2, Key.f5)
    )
    emote_thread5.start()


def emote_do(text, response, keyboard, startTime, key):
    num = is_array_contain_string(text, response)
    if num > 0:
        start = round(num * startTime, 2)
        time.sleep(start)
        keyboard.press(key)
        time.sleep(1)
        keyboard.release(key)
        print(f"{response}:输出表情({start}){key}")


def is_index_contain_string(string_array, target_string):
    i = 0
    for s in string_array:
        i = i + 1
        if s in target_string:
            num = target_string.find(s)
            return num + len(s)
    return 0


def is_array_contain_string(string_array, target_string):
    i = 0
    for s in string_array:
        i = i + 1
        if s in target_string:
            return i
    return 0


def check_mpv():
    """
    若mpv已经播放完毕且播放列表中有数据 则创建一个播放音频的线程
    :return:
    """
    global is_mpv_ready
    global MpvList
    if not MpvList.empty() and is_mpv_ready:
        is_mpv_ready = False
        tts_thread = threading.Thread(target=mpv_read())
        tts_thread.start()


def mpv_read():
    """
    按照MpvList内的名单播放音频直到播放完毕
    :return:
    """
    global MpvList
    global is_mpv_ready
    while not MpvList.empty():
        temp1 = MpvList.get()
        current_mpvlist_count = MpvList.qsize()

        # 表情加入:使用键盘控制VTube
        response = EmoteList.get()
        emote_thread = threading.Thread(target=emote_show(response))
        emote_thread.start()

        print(
            f"\033[32mSystem>>\033[0m开始播放output{temp1}.mp3，当前待播语音数：{current_mpvlist_count}"
        )
        subprocess.run(
            f"mpv.exe -vo null .\output\output{temp1}.mp3 1>nul", shell=True
        )  # 执行命令行指令
        subprocess.run(f"del /f .\output\output{temp1}.mp3 1>nul", shell=True)
    is_mpv_ready = True


def chat_response(prompt, history, past_key_values, return_past_key_values):
    current_length = 0
    stop_stream = False
    for response, history, past_key_values in model.stream_chat(
        tokenizer,
        prompt,
        history,
        past_key_values=past_key_values,
        return_past_key_values=return_past_key_values,
    ):
        if stop_stream:
            stop_stream = False
            break
        else:
            response[current_length:]
            current_length = len(response)
    return response, history


def main():
    sched1.add_job(check_answer, "interval", seconds=1, id=f"answer", max_instances=4)
    sched1.add_job(check_tts, "interval", seconds=1, id=f"tts", max_instances=4)
    sched1.add_job(check_mpv, "interval", seconds=1, id=f"mpv", max_instances=4)
    sched1.start()
    sync(room.connect())  # 开始监听弹幕流


if __name__ == "__main__":
    main()