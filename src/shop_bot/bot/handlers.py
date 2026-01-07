import logging
import uuid
import hashlib
import json
import urllib.parse
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlencode

from aiogram import Router, F, types, Bot
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shop_bot.data_manager.database import (
    get_user, get_plan_by_id, get_setting, create_pending_transaction,
    update_transaction_status, update_user_balance,
    get_promo_code, use_promo_code, create_user_key, get_user_keys,
    get_transaction_by_payment_id, get_host_by_name, get_key_by_id, update_key_expiry,
    register_user_if_not_exists, get_all_hosts, get_plans_for_host, mark_trial_used,
    get_latest_speedtest
)
from shop_bot.data_manager import speedtest_runner
from shop_bot.modules import xui_api
from shop_bot.bot import keyboards
from shop_bot.bot.states import PaymentProcess, TopUpProcess


logger = logging.getLogger(__name__)
user_router = Router()

@user_router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    
    # Определяем реферера
    referrer_id = None
    args = message.text.split()
    if len(args) > 1:
        try:
            potential_ref = int(args[1])
            if potential_ref != user.id:
                referrer_id = potential_ref
        except ValueError:
            pass
            
    # Регистрация пользователя (или обновление данных)
    register_user_if_not_exists(user.id, user.username, referrer_id)
    
    welcome_text = get_setting("main_menu_text") or "Добро пожаловать в бот продажи VPN!"
    
    # Клавиатура
    keys = get_user_keys(user.id)
    trial_enabled = get_setting("trial_enabled") == "true"
    admin_id_str = get_setting("admin_telegram_id")
    is_admin = str(user.id) == str(admin_id_str)
    
    kb = keyboards.create_main_menu_keyboard(keys, trial_enabled, is_admin)
    
    await message.answer(welcome_text, reply_markup=kb)

@user_router.callback_query(F.data == "main_menu")
@user_router.callback_query(F.data == "back_to_main_menu")
async def show_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    keys = get_user_keys(user_id)
    trial_enabled = get_setting("trial_enabled") == "true"
    admin_id_str = get_setting("admin_telegram_id")
    is_admin = str(user_id) == str(admin_id_str)
    
    welcome_text = get_setting("main_menu_text") or "Главное меню:"
    kb = keyboards.create_main_menu_keyboard(keys, trial_enabled, is_admin)
    
    await callback.message.edit_text(welcome_text, reply_markup=kb)

@user_router.callback_query(F.data == "get_trial")
async def get_trial_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if user.get('trial_used'):
        await callback.answer("Вы уже использовали пробный период!", show_alert=True)
        return

    trial_enabled = get_setting("trial_enabled") == "true"
    if not trial_enabled:
        await callback.answer("Пробный период отключен", show_alert=True)
        return

    hosts = get_all_hosts()
    if not hosts:
        await callback.answer("Нет доступных серверов для пробного периода", show_alert=True)
        return

    # Use the first host for trial
    host = hosts[0]
    days_str = get_setting("trial_duration_days")
    try:
        days = int(days_str) if days_str else 3
    except ValueError:
        days = 3
    
    # Generate email
    import random
    import string
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    email = f"trial_{user_id}_{suffix}"
    
    # Create key
    await callback.message.edit_text("⏳ Создаем пробный ключ...")
    
    try:
        client = await xui_api.create_or_update_key_on_host(host['host_name'], email, days_to_add=days)
        
        if client:
            # Mark trial used
            mark_trial_used(user_id)
            
            # Save to DB
            create_user_key(user_id, host['host_name'], client['client_uuid'], email, client['expiry_timestamp_ms'])
            
            msg = (
                f"🎁 <b>Ваш пробный ключ на {days} дн. готов!</b>\n\n"
                f"<code>{client['connection_string']}</code>\n\n"
                f"Инструкции по подключению в главном меню."
            )
            builder = InlineKeyboardBuilder()
            builder.button(text="🔙 В меню", callback_data="main_menu")
            await callback.message.edit_text(msg, reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await callback.message.edit_text("❌ Ошибка при создании ключа. Попробуйте позже.")
            
    except Exception as e:
        logger.error(f"Error creating trial key: {e}")
        await callback.message.edit_text("❌ Произошла ошибка. Обратитесь в поддержку.")

@user_router.callback_query(F.data == "show_profile")
async def show_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_data = get_user(user_id)
    if not user_data:
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        return

    keys = get_user_keys(user_id)
    balance = user_data.get('balance', 0)
    spent = user_data.get('total_spent', 0)
    
    text = (
        f"👤 <b>Ваш профиль:</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💰 Баланс: <b>{balance} RUB</b>\n"
        f"💸 Потрачено: <b>{spent} RUB</b>\n"
        f"🔑 Активных ключей: <b>{len(keys)}</b>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Пополнить баланс", callback_data="top_up_start")
    builder.button(text="🔙 Назад", callback_data="main_menu")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

@user_router.callback_query(F.data == "buy_new_key")
async def start_buy_process(callback: types.CallbackQuery, state: FSMContext):
    # Получаем список хостов/локаций
    hosts = get_all_hosts()
    if not hosts:
        await callback.answer("Нет доступных серверов", show_alert=True)
        return
        
    builder = InlineKeyboardBuilder()
    for host in hosts:
        # Используем токен для callback_data
        token = keyboards.encode_host_callback_token(host['host_name'])
        # Добавляем пустой extra параметр для корректного парсинга (action:extra:token)
        builder.button(text=host['host_name'], callback_data=f"select_host:buy::{token}")
    
    builder.button(text="🔙 Назад", callback_data="main_menu")
    builder.adjust(1)
    
    await callback.message.edit_text("🌍 Выберите локацию:", reply_markup=builder.as_markup())

@user_router.callback_query(F.data.startswith("select_host:buy:"))
async def select_host_handler(callback: types.CallbackQuery, state: FSMContext):
    parts = keyboards.parse_host_callback_data(callback.data)
    if not parts:
        await callback.answer("Ошибка данных", show_alert=True)
        return
    _, _, token = parts
    
    hosts = get_all_hosts()
    host = keyboards.find_host_by_callback_token(hosts, token)
    
    if not host:
        await callback.answer("Сервер не найден", show_alert=True)
        return
        
    # Сохраняем выбранный хост в состояние
    await state.update_data(host_name=host['host_name'], action="buy_key")
    
    # Получаем тарифы для хоста
    plans = get_plans_for_host(host['host_name'])
    if not plans:
        await callback.answer("Для этого сервера нет активных тарифов", show_alert=True)
        return
        
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.button(
            text=f"{plan['plan_name']} - {plan['price']}₽ ({plan['months']} мес.)", 
            callback_data=f"select_plan:{plan['plan_id']}"
        )
        
    builder.button(text="🔙 Назад", callback_data="buy_new_key")
    builder.adjust(1)
    
    await callback.message.edit_text(f"📋 Выберите тариф для {host['host_name']}:", reply_markup=builder.as_markup())

@user_router.callback_query(F.data.startswith("select_plan:"))
async def select_plan_handler(callback: types.CallbackQuery, state: FSMContext):
    plan_id_str = callback.data.split(":")[1]
    try:
        plan_id = int(plan_id_str)
    except ValueError:
        await callback.answer("Ошибка ID тарифа", show_alert=True)
        return
        
    plan = get_plan_by_id(plan_id)
    if not plan:
        await callback.answer("Тариф не найден", show_alert=True)
        return
        
    await state.update_data(plan_id=plan_id, price=plan['price'], months=plan['months'])
    
    # Переходим к оплате
    await show_payment_methods(callback, state)

async def show_payment_methods(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    plan_id = data.get('plan_id')
    plan = get_plan_by_id(plan_id)
    price = plan['price']
    
    builder = InlineKeyboardBuilder()
    
    # Кнопка оплаты балансом
    builder.button(text=f"💰 С баланса бота", callback_data="pay_balance")
    
    # Кнопки платежек (проверяем настройки)
    if get_setting("yookassa_shop_id") and get_setting("yookassa_secret_key"):
        builder.button(text="YooKassa (РФ карты)", callback_data="pay_yookassa")
        
    if get_setting("yoomoney_wallet"):
        builder.button(text="YooMoney (Кошелек/Карта)", callback_data="pay_yoomoney")

    if get_setting("unitpay_public_key"):
        builder.button(text="Unitpay", callback_data="pay_unitpay")
        
    if get_setting("freekassa_shop_id"):
        builder.button(text="FreeKassa (Crypto/Cards)", callback_data="pay_freekassa")
        
    builder.button(text="🔙 Назад", callback_data="main_menu")
    builder.adjust(1)
    
    await state.set_state(PaymentProcess.waiting_for_payment_method)
    await callback.message.edit_text(
        f"💳 К оплате: <b>{price} RUB</b>\n"
        f"Тариф: {plan['plan_name']}\n"
        f"Выберите способ оплаты:",
        reply_markup=builder.as_markup()
    )

@user_router.callback_query(PaymentProcess.waiting_for_payment_method, F.data == "pay_balance")
async def pay_with_balance(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = get_user(user_id)
    data = await state.get_data()
    
    price = float(data.get('price', 0))
    balance = float(user_data.get('balance', 0))
    
    if balance < price:
        await callback.answer("Недостаточно средств на балансе", show_alert=True)
        return
        
    # Списываем баланс и выдаем ключ
    new_balance = update_user_balance(user_id, -price)
    
    # Создаем фиктивную транзакцию для истории
    payment_id = str(uuid.uuid4())
    metadata = {
        "payment_id": payment_id,
        "user_id": user_id,
        "price": price,
        "action": data.get('action'),
        "key_id": data.get('key_id'),
        "host_name": data.get('host_name'),
        "plan_id": data.get('plan_id'),
        "months": data.get('months'),
        "payment_method": "Balance"
    }
    create_pending_transaction(payment_id, user_id, price, metadata)
    
    # Сразу обрабатываем как успешный платеж
    await process_successful_payment(callback.bot, metadata)
    await state.clear()
    
    # Возвращаем в меню (process_successful_payment отправит сообщение с ключом)
    # Можно отправить дополнительное уведомление или просто обновить меню
    # await show_main_menu(callback, state) # process_successful_payment отправляет новое сообщение, так что тут просто ответим
    await callback.answer()

@user_router.callback_query(F.data == "top_up_start")
async def start_top_up(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(TopUpProcess.waiting_for_topup_amount)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data="main_menu")
    await callback.message.edit_text("Введите сумму пополнения в RUB:", reply_markup=builder.as_markup())

@user_router.message(TopUpProcess.waiting_for_topup_amount)
async def process_top_up_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число (больше 0).")
        return
        
    await state.update_data(topup_amount=amount)
    
    builder = InlineKeyboardBuilder()
    if get_setting("yookassa_shop_id"):
        builder.button(text="YooKassa", callback_data="topup_pay_yookassa")
    if get_setting("yoomoney_wallet"):
        builder.button(text="YooMoney", callback_data="topup_pay_yoomoney")
    if get_setting("unitpay_public_key"):
        builder.button(text="Unitpay", callback_data="topup_pay_unitpay")
    if get_setting("freekassa_shop_id"):
        builder.button(text="FreeKassa", callback_data="topup_pay_freekassa")
        
    builder.button(text="🔙 Назад", callback_data="main_menu")
    builder.adjust(1)
    
    await state.set_state(TopUpProcess.waiting_for_topup_method)
    await message.answer(f"Сумма пополнения: {amount} RUB.\nВыберите способ оплаты:", reply_markup=builder.as_markup())

@user_router.callback_query(F.data == "show_help")
async def show_help(callback: types.CallbackQuery):
    help_text = get_setting("support_text") or (
        "🆘 <b>Поддержка</b>\n\n"
        "Если у вас возникли вопросы или проблемы при использовании сервиса, "
        "пожалуйста, обратитесь в нашу службу поддержки."
    )
    support_url = get_setting("support_url")
    support_user = get_setting("support_user")
    
    builder = InlineKeyboardBuilder()
    if support_url:
        builder.button(text="Написать в поддержку", url=support_url)
    elif support_user:
        builder.button(text="Написать в поддержку", url=f"https://t.me/{support_user.lstrip('@')}")
    builder.button(text="🔙 Назад", callback_data="main_menu")
    builder.adjust(1)
    
    await callback.message.edit_text(help_text, reply_markup=builder.as_markup(), parse_mode="HTML")

@user_router.callback_query(F.data == "show_about")
async def show_about(callback: types.CallbackQuery):
    about_text = get_setting("about_text")
    if not about_text:
        about_text = (
            "ℹ️ <b>О проекте</b>\n\n"
            "Этот бот позволяет автоматически приобретать и управлять ключами доступа VLESS VPN. "
            "Мы используем современные протоколы для обеспечения безопасности и скорости вашего соединения."
        )
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="main_menu")
    await callback.message.edit_text(about_text, reply_markup=builder.as_markup(), parse_mode="HTML")

@user_router.callback_query(F.data == "howto_vless")
async def show_howto(callback: types.CallbackQuery):
    text = (
        "❓ <b>Как использовать</b>\n\n"
        "Выберите вашу платформу, чтобы увидеть инструкцию."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text=(get_setting("btn_howto_android") or "📱 Android"), callback_data="howto_android")
    builder.button(text=(get_setting("btn_howto_ios") or "📱 iOS"), callback_data="howto_ios")
    builder.button(text=(get_setting("btn_howto_windows") or "💻 Windows"), callback_data="howto_windows")
    builder.button(text=(get_setting("btn_howto_linux") or "🐧 Linux"), callback_data="howto_linux")
    builder.button(text="🔙 Назад", callback_data="main_menu")
    builder.adjust(2, 2, 1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@user_router.callback_query(F.data == "howto_android")
async def show_howto_android(callback: types.CallbackQuery):
    txt = get_setting("howto_android_text") or "Инструкция для Android скоро будет доступна."
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="howto_vless")
    await callback.message.edit_text(txt, reply_markup=builder.as_markup(), parse_mode="HTML")

@user_router.callback_query(F.data == "howto_ios")
async def show_howto_ios(callback: types.CallbackQuery):
    txt = get_setting("howto_ios_text") or "Инструкция для iOS скоро будет доступна."
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="howto_vless")
    await callback.message.edit_text(txt, reply_markup=builder.as_markup(), parse_mode="HTML")

@user_router.callback_query(F.data == "howto_windows")
async def show_howto_windows(callback: types.CallbackQuery):
    txt = get_setting("howto_windows_text") or "Инструкция для Windows скоро будет доступна."
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="howto_vless")
    await callback.message.edit_text(txt, reply_markup=builder.as_markup(), parse_mode="HTML")

@user_router.callback_query(F.data == "howto_linux")
async def show_howto_linux(callback: types.CallbackQuery):
    txt = get_setting("howto_linux_text") or "Инструкция для Linux скоро будет доступна."
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="howto_vless")
    await callback.message.edit_text(txt, reply_markup=builder.as_markup(), parse_mode="HTML")

@user_router.callback_query(F.data == "manage_keys")
async def show_user_keys(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    try:
        keys = get_user_keys(user_id)
        
        if not keys:
            await callback.answer("У вас пока нет активных ключей", show_alert=True)
            return
            
        builder = InlineKeyboardBuilder()
        for key in keys:
                    label = f"{key.get('key_email', 'Key')} ({key.get('host_name', 'Host')})"
                    builder.button(text=label, callback_data=f"view_key:{key['key_id']}")
        
        builder.button(text="🔙 В меню", callback_data="main_menu")
        builder.adjust(1)
        
        # Try to edit the message, if fails (e.g. old message), send new one
        try:
            await callback.message.edit_text("📂 <b>Ваши ключи:</b>\nВыберите ключ для просмотра информации:", reply_markup=builder.as_markup(), parse_mode="HTML")
        except Exception:
            await callback.message.delete()
            await callback.message.answer("📂 <b>Ваши ключи:</b>\nВыберите ключ для просмотра информации:", reply_markup=builder.as_markup(), parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error in show_user_keys: {e}", exc_info=True)
        await callback.answer("Произошла ошибка при загрузке ключей", show_alert=True)

@user_router.callback_query(F.data.startswith("view_key:"))
async def view_key_handler(callback: types.CallbackQuery):
    try:
        key_id = int(callback.data.split(":")[1])
        key = get_key_by_id(key_id)
        
        if not key:
            await callback.answer("Ключ не найден", show_alert=True)
            # Refresh list
            await show_user_keys(callback)
            return

        # Show loading status while fetching details
        try:
            await callback.message.edit_text("⏳ Загрузка данных ключа...", reply_markup=None)
        except Exception:
            pass

        try:
            expiry_ts = key.get('expiry_time')
            if expiry_ts and isinstance(expiry_ts, (int, float)) and expiry_ts > 0:
                expiry = datetime.fromtimestamp(expiry_ts/1000).strftime('%Y-%m-%d %H:%M')
            else:
                expiry = "Бессрочно"
        except Exception as e:
            logger.warning(f"Error parsing expiry for key {key.get('key_id')}: {e}")
            expiry = "Неизвестно"
        
        key_email = key.get('key_email', 'Unknown')
        host_name = key.get('host_name', 'Unknown')
        
        connection_display = key.get('access_url')
        if not connection_display:
            try:
                details = await xui_api.get_key_details_from_host(key)
                if details and details.get('connection_string'):
                    connection_display = details['connection_string']
            except Exception as e:
                logger.warning(f"Failed to get key details for key {key.get('key_id')}: {e}")
                connection_display = None
        
        text = (
            f"🔑 <b>Ключ:</b> {key_email}\n"
            f"🌍 <b>Сервер:</b> {host_name}\n"
            f"⏳ <b>Истекает:</b> {expiry}\n"
            f"🔗 <code>{connection_display or 'Ссылка недоступна'}</code>"
        )
        
        builder = InlineKeyboardBuilder()
        builder.button(text="📅 Продлить", callback_data=f"renew_key:{key['key_id']}")
        builder.button(text="🔙 К списку ключей", callback_data="manage_keys")
        builder.button(text="🏠 Главное меню", callback_data="main_menu")
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in view_key_handler: {e}", exc_info=True)
        await callback.answer("Ошибка при отображении ключа", show_alert=True)

@user_router.callback_query(F.data.startswith("renew_key:"))
async def renew_key_handler(callback: types.CallbackQuery, state: FSMContext):
    try:
        key_id_str = callback.data.split(":")[1]
        key_id = int(key_id_str)
    except (ValueError, IndexError):
        await callback.answer("Ошибка ID ключа", show_alert=True)
        return

    key_data = get_key_by_id(key_id)
    if not key_data:
        await callback.answer("Ключ не найден", show_alert=True)
        return

    # Сохраняем контекст продления
    await state.update_data(
        action="renew_key",
        key_id=key_id,
        host_name=key_data['host_name'],
        customer_email=key_data['key_email']
    )

    # Получаем тарифы для хоста
    plans = get_plans_for_host(key_data['host_name'])
    if not plans:
        await callback.answer("Нет доступных тарифов для продления", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.button(
            text=f"{plan['plan_name']} - {plan['price']}₽ ({plan['months']} мес.)",
            callback_data=f"select_plan:{plan['plan_id']}"
        )
    
    builder.button(text="🔙 Отмена", callback_data="main_menu")
    builder.adjust(1)
    
    await callback.message.answer(
        f"🔄 <b>Продление ключа:</b> {key_data['key_email']}\n"
        f"Сервер: {key_data['host_name']}\n\n"
        f"Выберите тариф:", 
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@user_router.callback_query(F.data == "show_referral_program")
async def show_referral_program(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    bot_username = (await callback.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    
    ref_count = 0 # TODO: Добавить функцию подсчета рефералов
    ref_balance = user.get('referral_balance', 0)
    
    # Получаем шаблон текста из настроек или используем дефолтный
    template = get_setting("referral_text")
    if not template:
        template = (
            "🤝 <b>Реферальная программа</b>\n\n"
            "Приглашайте друзей и получайте бонусы!\n"
            "Ваша ссылка:\n<code>{link}</code>\n\n"
            "👥 Приглашено: {count}\n"
            "💰 Бонусный баланс: {balance} RUB"
        )
    
    # Заменяем плейсхолдеры
    text = template.replace("{link}", ref_link)\
                   .replace("{count}", str(ref_count))\
                   .replace("{balance}", str(ref_balance))
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="main_menu")
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@user_router.callback_query(F.data == "user_speedtest")
async def run_user_speedtest(callback: types.CallbackQuery):
    logger.info(f"SPEEDTEST: Handler called by user {callback.from_user.id}")
    try:
        # Получаем список хостов
        hosts = get_all_hosts() or []
        if not hosts:
            await callback.answer("⚠️ Хосты не найдены в настройках.", show_alert=True)
            return
        
        # Показываем последние результаты тестов скорости для всех хостов
        text = "⚡️ <b>Результаты Speedtest</b>\n"
        text += "<i>Нажмите кнопку «Обновить», чтобы запустить новый тест (это может занять время).</i>\n\n"
        
        for host in hosts:
            host_name = host.get('host_name', 'Неизвестный хост')
            latest_test = get_latest_speedtest(host_name)
            
            if latest_test:
                ping = latest_test.get('ping_ms')
                download = latest_test.get('download_mbps')
                upload = latest_test.get('upload_mbps')
                method = latest_test.get('method', 'unknown').upper()
                created_at = latest_test.get('created_at', '—')
                
                # Форматируем время
                try:
                    if created_at and created_at != '—':
                        if isinstance(created_at, str):
                            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        else:
                            dt = created_at
                        time_str = dt.strftime('%d.%m %H:%M')
                    else:
                        time_str = '—'
                except Exception:
                    time_str = str(created_at)
                
                # Форматируем значения
                ping_str = f"{ping:.2f}" if ping is not None else "—"
                download_str = f"{download:.0f}" if download is not None else "—"
                upload_str = f"{upload:.0f}" if upload is not None else "—"
                
                text += f"• 🌏 <b>{host_name}</b> ({method})\n"
                text += f"   ✅ Ping: {ping_str} ms\n"
                text += f"   ⬇️ Download: {download_str} Mbps\n"
                text += f"   ⬆️ Upload: {upload_str} Mbps\n"
                text += f"   🕒 {time_str}\n\n"
            else:
                text += f"• 🌏 <b>{host_name}</b> — Нет данных\n\n"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Обновить", callback_data="refresh_speedtest")
        builder.button(text="🔙 Назад", callback_data="main_menu")
        builder.adjust(1)
        
        # Если это callback от кнопки "Обновить", редактируем сообщение, иначе отправляем/редактируем
        if callback.message:
            await callback.message.edit_text(
                text,
                reply_markup=builder.as_markup(),
                disable_web_page_preview=True,
                parse_mode="HTML"
            )
        else:
            await callback.answer(text, show_alert=True) # Fallback if something weird happens

    except Exception as e:
        logger.error(f"Error in user_speedtest: {e}")
        await callback.answer("Произошла ошибка при получении данных.", show_alert=True)


@user_router.callback_query(F.data == "refresh_speedtest")
async def refresh_speedtest_handler(callback: types.CallbackQuery):
    await callback.answer("⏳ Запускаем тесты скорости... Это может занять 1-2 минуты.", show_alert=True)
    
    try:
        hosts = get_all_hosts() or []
        if not hosts:
            return

        # Запускаем тесты для всех хостов
        # Лучше делать это асинхронно, но здесь мы просто подождем
        # В идеале нужно использовать background task, но для простоты сделаем await
        for host in hosts:
            host_name = host.get('host_name')
            if host_name:
                try:
                    # Используем run_both_for_host из speedtest_runner
                    # Оборачиваем в timeout чтобы не висело вечно
                    async with asyncio.timeout(60):
                        await speedtest_runner.run_both_for_host(host_name)
                except Exception as e:
                    logger.error(f"Manual speedtest failed for {host_name}: {e}")
        
        # После завершения вызываем отображение результатов
        await run_user_speedtest(callback)
        
    except Exception as e:
        logger.error(f"Error in refresh_speedtest: {e}")
        await callback.message.answer("Произошла ошибка при обновлении данных.")


PAYMENT_METHODS = {}



# --- Successful Payment Processor ---
async def process_successful_payment(bot: Bot, metadata: dict):
    """
    Обработка успешного платежа.
    metadata: словарь с данными платежа (user_id, action, amount, payment_id, etc.)
    """
    try:
        payment_id = metadata.get('payment_id')
        user_id = int(metadata.get('user_id'))
        action = metadata.get('action')
        amount = float(metadata.get('price', 0))
        
        logger.info(f"Processing payment {payment_id} for user {user_id}, action: {action}, amount: {amount}")
        
        # Обновляем статус транзакции
        update_transaction_status(payment_id, 'paid')
        
        if action == 'top_up':
            # Пополнение баланса
            new_balance = update_user_balance(user_id, amount)
            await bot.send_message(
                chat_id=user_id,
                text=f"✅ Баланс успешно пополнен на {amount} RUB.\nТекущий баланс: {new_balance} RUB"
            )
            
        else:
            # Покупка или продление ключа
            plan_id = metadata.get('plan_id')
            months = int(metadata.get('months', 1))
            host_name = metadata.get('host_name')
            email = metadata.get('customer_email')
            key_id = metadata.get('key_id')
            
            if key_id:
                # Продление существующего ключа
                key_data = get_key_by_id(key_id)
                if key_data:
                    # Используем create_or_update_key_on_host для продления
                    # days_to_add = months * 30 (примерно)
                    days = months * 30
                    result = await xui_api.create_or_update_key_on_host(
                        key_data['host_name'], 
                        key_data['key_email'], 
                        days_to_add=days
                    )
                    
                    if result:
                        update_key_expiry(key_id, result['expiry_timestamp_ms'])
                        await bot.send_message(
                            chat_id=user_id, 
                            text=f"✅ Ключ успешно продлен на {months} мес.\nНовая дата окончания: {datetime.fromtimestamp(result['expiry_timestamp_ms']/1000).strftime('%Y-%m-%d %H:%M')}"
                        )
                    else:
                        await bot.send_message(chat_id=user_id, text="❌ Ошибка при продлении ключа на сервере. Обратитесь в поддержку.")
                else:
                    await bot.send_message(chat_id=user_id, text="❌ Ключ не найден в базе данных.")
            else:
                # Создание нового ключа
                # Генерируем email если нет
                if not email:
                    import random
                    import string
                    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
                    email = f"user_{user_id}_{suffix}"
                
                # Создаем ключ в панели
                # Используем create_or_update_key_on_host для создания
                days = months * 30
                client = await xui_api.create_or_update_key_on_host(
                    host_name, 
                    email, 
                    days_to_add=days
                )
                
                if client:
                    # Сохраняем в БД
                    # create_or_update_key_on_host возвращает dict с client_uuid и expiry_timestamp_ms
                    create_user_key(user_id, host_name, client['client_uuid'], email, client['expiry_timestamp_ms'])
                    
                    # Отправляем ключ пользователю
                    msg = (
                        f"✅ Оплата прошла успешно!\n\n"
                        f"Ваш ключ доступа:\n<code>{client['connection_string']}</code>\n\n"
                        f"Инструкции по настройке доступны в главном меню."
                    )
                    await bot.send_message(chat_id=user_id, text=msg, parse_mode="HTML")
                else:
                    await bot.send_message(chat_id=user_id, text="✅ Оплата прошла, но возникла ошибка при создании ключа. Обратитесь в поддержку.")
                    logger.error(f"Failed to create client for payment {payment_id}")

            # Применяем промокод если был
            promo_code = metadata.get('promo_code')
            if promo_code:
                use_promo_code(promo_code, user_id)

    except Exception as e:
        logger.error(f"Error processing payment {metadata}: {e}", exc_info=True)


# --- YooMoney Handlers ---
@user_router.callback_query(PaymentProcess.waiting_for_payment_method, F.data == "pay_yoomoney")
async def create_yoomoney_payment_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Создаю ссылку YooMoney...")
    data = await state.get_data()
    user_data = get_user(callback.from_user.id)
    plan = get_plan_by_id(data.get('plan_id'))
    if not plan:
        await callback.message.edit_text("❌ Произошла ошибка при выборе тарифа.")
        await state.clear()
        return
    
    base_price = Decimal(str(plan['price']))
    price_rub = base_price
    if user_data and user_data.get('referred_by') and user_data.get('total_spent', 0) == 0:
        try:
            discount_percentage = Decimal(get_setting("referral_discount") or "0")
        except Exception:
            discount_percentage = Decimal("0")
        if discount_percentage > 0:
            price_rub = base_price - (base_price * discount_percentage / 100).quantize(Decimal("0.01"))
    
    final_price_decimal = price_rub
    try:
        final_price_from_state = data.get('final_price')
        if final_price_from_state is not None:
            final_price_decimal = Decimal(str(final_price_from_state)).quantize(Decimal("0.01"))
    except Exception:
        pass
    if final_price_decimal < Decimal('0'):
        final_price_decimal = Decimal('0.00')
        
    final_price_float = float(final_price_decimal)
    
    wallet = (get_setting("yoomoney_wallet") or "").strip()
    if not wallet:
        await callback.message.edit_text("❌ Оплата через YooMoney временно недоступна (не настроен кошелек).")
        await state.clear()
        return
        
    months = int(plan['months'])
    user_id = callback.from_user.id
    payment_id = str(uuid.uuid4())
    
    metadata = {
        "payment_id": payment_id,
        "user_id": user_id,
        "months": months,
        "price": final_price_float,
        "action": data.get('action'),
        "key_id": data.get('key_id'),
        "host_name": data.get('host_name'),
        "plan_id": data.get('plan_id'),
        "customer_email": data.get('customer_email'),
        "payment_method": "YooMoney",
        "promo_code": data.get('promo_code'),
        "promo_discount_percent": data.get('promo_discount_percent'),
        "promo_discount_amount": data.get('promo_discount_amount'),
    }
    
    try:
        create_pending_transaction(payment_id, user_id, final_price_float, metadata)
    except Exception as e:
        logger.warning(f"YooMoney: не удалось создать ожидающую транзакцию: {e}")
        
    desc = f"Оплата {months} мес. (User {user_id})"
    # label в YooMoney используется как идентификатор платежа
    pay_url = _build_yoomoney_url(wallet, final_price_float, payment_id, desc)
    
    await state.clear()
    await callback.message.edit_text(
        "Нажмите на кнопку ниже для оплаты (YooMoney):",
        reply_markup=keyboards.create_payment_keyboard(pay_url)
    )

@user_router.callback_query(TopUpProcess.waiting_for_topup_method, F.data == "topup_pay_yoomoney")
async def topup_pay_yoomoney(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Готовлю YooMoney...")
    data = await state.get_data()
    amount = Decimal(str(data.get('topup_amount', 0)))
    if amount <= 0:
        await callback.message.edit_text("❌ Некорректная сумма пополнения.")
        await state.clear()
        return
        
    wallet = (get_setting("yoomoney_wallet") or "").strip()
    if not wallet:
        await callback.message.edit_text("❌ Оплата через YooMoney временно недоступна.")
        await state.clear()
        return

    user_id = callback.from_user.id
    payment_id = str(uuid.uuid4())
    metadata = {
        "payment_id": payment_id,
        "user_id": user_id,
        "price": float(amount),
        "action": "top_up",
        "payment_method": "YooMoney",
    }
    try:
        create_pending_transaction(payment_id, user_id, float(amount), metadata)
    except Exception as e:
        logger.warning(f"YooMoney topup: не удалось создать ожидающую транзакцию: {e}")
        
    desc = f"Пополнение баланса (User {user_id})"
    pay_url = _build_yoomoney_url(wallet, float(amount), payment_id, desc)
    
    await state.clear()
    await callback.message.edit_text(
        "Нажмите на кнопку ниже для оплаты (YooMoney):",
        reply_markup=keyboards.create_payment_keyboard(pay_url)
    )

def _build_yoomoney_url(wallet: str, amount: float, label: str, desc: str) -> str:
    # https://yoomoney.ru/quickpay/confirm.xml
    # receiver, quickpay-form, targets, paymentType, sum, label
    qs = urlencode({
        "receiver": wallet,
        "quickpay-form": "shop",
        "targets": desc,
        "paymentType": "PC", # PC = ЮMoney кошелек, AC = карта
        "sum": f"{amount:.2f}",
        "label": label
    })
    return f"https://yoomoney.ru/quickpay/confirm.xml?{qs}"


# --- Unitpay Handlers ---
@user_router.callback_query(PaymentProcess.waiting_for_payment_method, F.data == "pay_unitpay")
async def create_unitpay_payment_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Создаю ссылку Unitpay...")
    data = await state.get_data()
    user_data = get_user(callback.from_user.id)
    plan = get_plan_by_id(data.get('plan_id'))
    if not plan:
        await callback.message.edit_text("❌ Произошла ошибка при выборе тарифа.")
        await state.clear()
        return
    
    base_price = Decimal(str(plan['price']))
    price_rub = base_price
    if user_data and user_data.get('referred_by') and user_data.get('total_spent', 0) == 0:
        try:
            discount_percentage = Decimal(get_setting("referral_discount") or "0")
        except Exception:
            discount_percentage = Decimal("0")
        if discount_percentage > 0:
            price_rub = base_price - (base_price * discount_percentage / 100).quantize(Decimal("0.01"))
    
    final_price_decimal = price_rub
    try:
        final_price_from_state = data.get('final_price')
        if final_price_from_state is not None:
            final_price_decimal = Decimal(str(final_price_from_state)).quantize(Decimal("0.01"))
    except Exception:
        pass
    if final_price_decimal < Decimal('0'):
        final_price_decimal = Decimal('0.00')
        
    final_price_float = float(final_price_decimal)
    
    public_key = (get_setting("unitpay_public_key") or "").strip()
    secret_key = (get_setting("unitpay_secret_key") or "").strip()
    domain = (get_setting("unitpay_domain") or "unitpay.money").strip()
    
    if not public_key or not secret_key:
        await callback.message.edit_text("❌ Оплата через Unitpay временно недоступна.")
        await state.clear()
        return
        
    months = int(plan['months'])
    user_id = callback.from_user.id
    payment_id = str(uuid.uuid4())
    
    metadata = {
        "payment_id": payment_id,
        "user_id": user_id,
        "months": months,
        "price": final_price_float,
        "action": data.get('action'),
        "key_id": data.get('key_id'),
        "host_name": data.get('host_name'),
        "plan_id": data.get('plan_id'),
        "customer_email": data.get('customer_email'),
        "payment_method": "Unitpay",
        "promo_code": data.get('promo_code'),
        "promo_discount_percent": data.get('promo_discount_percent'),
        "promo_discount_amount": data.get('promo_discount_amount'),
    }
    
    try:
        create_pending_transaction(payment_id, user_id, final_price_float, metadata)
    except Exception as e:
        logger.warning(f"Unitpay: не удалось создать ожидающую транзакцию: {e}")
        
    desc = f"Оплата {months} мес."
    pay_url = _build_unitpay_url(domain, public_key, secret_key, final_price_float, payment_id, desc)
    
    await state.clear()
    await callback.message.edit_text(
        "Нажмите на кнопку ниже для оплаты:",
        reply_markup=keyboards.create_payment_keyboard(pay_url)
    )

@user_router.callback_query(TopUpProcess.waiting_for_topup_method, F.data == "topup_pay_unitpay")
async def topup_pay_unitpay(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Готовлю Unitpay...")
    data = await state.get_data()
    amount = Decimal(str(data.get('topup_amount', 0)))
    if amount <= 0:
        await callback.message.edit_text("❌ Некорректная сумма пополнения.")
        await state.clear()
        return
        
    public_key = (get_setting("unitpay_public_key") or "").strip()
    secret_key = (get_setting("unitpay_secret_key") or "").strip()
    domain = (get_setting("unitpay_domain") or "unitpay.money").strip()
    
    if not public_key or not secret_key:
        await callback.message.edit_text("❌ Оплата через Unitpay временно недоступна.")
        await state.clear()
        return

    user_id = callback.from_user.id
    payment_id = str(uuid.uuid4())
    metadata = {
        "payment_id": payment_id,
        "user_id": user_id,
        "price": float(amount),
        "action": "top_up",
        "payment_method": "Unitpay",
    }
    try:
        create_pending_transaction(payment_id, user_id, float(amount), metadata)
    except Exception as e:
        logger.warning(f"Unitpay topup: не удалось создать ожидающую транзакцию: {e}")
        
    desc = f"Пополнение на {amount:.2f} RUB"
    pay_url = _build_unitpay_url(domain, public_key, secret_key, float(amount), payment_id, desc)
    
    await state.clear()
    await callback.message.edit_text(
        "Нажмите на кнопку ниже для оплаты:",
        reply_markup=keyboards.create_payment_keyboard(pay_url)
    )

def _build_unitpay_url(domain: str, public_key: str, secret_key: str, amount: float, account: str, desc: str) -> str:
    # Unitpay signature: sha256(params + secret) where params are sorted alphabetically
    # Required params for signature: account, desc, sum
    # sum should be string, e.g. "10.00"
    sum_str = f"{amount:.2f}"
    
    # params dict for signature
    params = {
        "account": account,
        "desc": desc,
        "sum": sum_str
    }
    
    # Sort keys
    sorted_keys = sorted(params.keys())
    # Join values
    vals = [params[k] for k in sorted_keys]
    vals.append(secret_key)
    joined = "{up}".join(vals)
    
    import hashlib
    signature = hashlib.sha256(joined.encode('utf-8')).hexdigest()
    
    # Build URL
    # https://{domain}/pay/{public_key}?sum={sum}&account={account}&desc={desc}&signature={signature}
    qs = urlencode({
        "sum": sum_str,
        "account": account,
        "desc": desc,
        "signature": signature
    })
    return f"https://{domain}/pay/{public_key}?{qs}"

# --- Freekassa Handlers ---
@user_router.callback_query(PaymentProcess.waiting_for_payment_method, F.data == "pay_freekassa")
async def create_freekassa_payment_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Создаю ссылку Freekassa...")
    data = await state.get_data()
    user_data = get_user(callback.from_user.id)
    plan = get_plan_by_id(data.get('plan_id'))
    if not plan:
        await callback.message.edit_text("❌ Произошла ошибка при выборе тарифа.")
        await state.clear()
        return
    
    base_price = Decimal(str(plan['price']))
    price_rub = base_price
    if user_data and user_data.get('referred_by') and user_data.get('total_spent', 0) == 0:
        try:
            discount_percentage = Decimal(get_setting("referral_discount") or "0")
        except Exception:
            discount_percentage = Decimal("0")
        if discount_percentage > 0:
            price_rub = base_price - (base_price * discount_percentage / 100).quantize(Decimal("0.01"))
    
    final_price_decimal = price_rub
    try:
        final_price_from_state = data.get('final_price')
        if final_price_from_state is not None:
            final_price_decimal = Decimal(str(final_price_from_state)).quantize(Decimal("0.01"))
    except Exception:
        pass
    if final_price_decimal < Decimal('0'):
        final_price_decimal = Decimal('0.00')
        
    final_price_float = float(final_price_decimal)
    
    shop_id = (get_setting("freekassa_shop_id") or "").strip()
    secret_key = (get_setting("freekassa_api_key") or "").strip() # secret_key_1 usually used for signature form
    
    if not shop_id or not secret_key:
        await callback.message.edit_text("❌ Оплата через Freekassa временно недоступна.")
        await state.clear()
        return
        
    months = int(plan['months'])
    user_id = callback.from_user.id
    payment_id = str(uuid.uuid4())
    
    metadata = {
        "payment_id": payment_id,
        "user_id": user_id,
        "months": months,
        "price": final_price_float,
        "action": data.get('action'),
        "key_id": data.get('key_id'),
        "host_name": data.get('host_name'),
        "plan_id": data.get('plan_id'),
        "customer_email": data.get('customer_email'),
        "payment_method": "Freekassa",
        "promo_code": data.get('promo_code'),
        "promo_discount_percent": data.get('promo_discount_percent'),
        "promo_discount_amount": data.get('promo_discount_amount'),
    }
    
    try:
        create_pending_transaction(payment_id, user_id, final_price_float, metadata)
    except Exception as e:
        logger.warning(f"Freekassa: не удалось создать ожидающую транзакцию: {e}")
        
    pay_url = _build_freekassa_url(shop_id, secret_key, final_price_float, payment_id)
    
    await state.clear()
    await callback.message.edit_text(
        "Нажмите на кнопку ниже для оплаты:",
        reply_markup=keyboards.create_payment_keyboard(pay_url)
    )

@user_router.callback_query(TopUpProcess.waiting_for_topup_method, F.data == "topup_pay_freekassa")
async def topup_pay_freekassa(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Готовлю Freekassa...")
    data = await state.get_data()
    amount = Decimal(str(data.get('topup_amount', 0)))
    if amount <= 0:
        await callback.message.edit_text("❌ Некорректная сумма пополнения.")
        await state.clear()
        return
        
    shop_id = (get_setting("freekassa_shop_id") or "").strip()
    secret_key = (get_setting("freekassa_api_key") or "").strip()
    
    if not shop_id or not secret_key:
        await callback.message.edit_text("❌ Оплата через Freekassa временно недоступна.")
        await state.clear()
        return

    user_id = callback.from_user.id
    payment_id = str(uuid.uuid4())
    metadata = {
        "payment_id": payment_id,
        "user_id": user_id,
        "price": float(amount),
        "action": "top_up",
        "payment_method": "Freekassa",
    }
    try:
        create_pending_transaction(payment_id, user_id, float(amount), metadata)
    except Exception as e:
        logger.warning(f"Freekassa topup: не удалось создать ожидающую транзакцию: {e}")
        
    pay_url = _build_freekassa_url(shop_id, secret_key, float(amount), payment_id)
    
    await state.clear()
    await callback.message.edit_text(
        "Нажмите на кнопку ниже для оплаты:",
        reply_markup=keyboards.create_payment_keyboard(pay_url)
    )

def _build_freekassa_url(shop_id: str, secret_key: str, amount: float, order_id: str) -> str:
    # Signature: md5(shop_id:amount:secret_key:currency:order_id)
    currency = "RUB"
    amount_str = f"{amount:.2f}" # Freekassa expects amount as is, usually dot separated
    
    raw = f"{shop_id}:{amount_str}:{secret_key}:{currency}:{order_id}"
    import hashlib
    sign = hashlib.md5(raw.encode('utf-8')).hexdigest()
    
    qs = urlencode({
        "m": shop_id,
        "oa": amount_str,
        "o": order_id,
        "s": sign,
        "currency": currency
    })
    return f"https://pay.freekassa.ru/?{qs}"

# --- Enot.io Handlers ---
@user_router.callback_query(PaymentProcess.waiting_for_payment_method, F.data == "pay_enot")
async def create_enot_payment_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Создаю ссылку Enot.io...")
    data = await state.get_data()
    user_data = get_user(callback.from_user.id)
    plan = get_plan_by_id(data.get('plan_id'))
    if not plan:
        await callback.message.edit_text("❌ Произошла ошибка при выборе тарифа.")
        await state.clear()
        return
    
    base_price = Decimal(str(plan['price']))
    price_rub = base_price
    if user_data and user_data.get('referred_by') and user_data.get('total_spent', 0) == 0:
        try:
            discount_percentage = Decimal(get_setting("referral_discount") or "0")
        except Exception:
            discount_percentage = Decimal("0")
        if discount_percentage > 0:
            price_rub = base_price - (base_price * discount_percentage / 100).quantize(Decimal("0.01"))
    
    final_price_decimal = price_rub
    try:
        final_price_from_state = data.get('final_price')
        if final_price_from_state is not None:
            final_price_decimal = Decimal(str(final_price_from_state)).quantize(Decimal("0.01"))
    except Exception:
        pass
    if final_price_decimal < Decimal('0'):
        final_price_decimal = Decimal('0.00')
        
    final_price_float = float(final_price_decimal)
    
    shop_id = (get_setting("enot_shop_id") or "").strip()
    secret_key = (get_setting("enot_secret_key") or "").strip()
    
    if not shop_id or not secret_key:
        await callback.message.edit_text("❌ Оплата через Enot.io временно недоступна.")
        await state.clear()
        return
        
    months = int(plan['months'])
    user_id = callback.from_user.id
    payment_id = str(uuid.uuid4())
    
    metadata = {
        "payment_id": payment_id,
        "user_id": user_id,
        "months": months,
        "price": final_price_float,
        "action": data.get('action'),
        "key_id": data.get('key_id'),
        "host_name": data.get('host_name'),
        "plan_id": data.get('plan_id'),
        "customer_email": data.get('customer_email'),
        "payment_method": "Enot.io",
        "promo_code": data.get('promo_code'),
        "promo_discount_percent": data.get('promo_discount_percent'),
        "promo_discount_amount": data.get('promo_discount_amount'),
    }
    
    try:
        create_pending_transaction(payment_id, user_id, final_price_float, metadata)
    except Exception as e:
        logger.warning(f"Enot: не удалось создать ожидающую транзакцию: {e}")
        
    pay_url = _build_enot_url(shop_id, secret_key, final_price_float, payment_id)
    
    await state.clear()
    await callback.message.edit_text(
        "Нажмите на кнопку ниже для оплаты:",
        reply_markup=keyboards.create_payment_keyboard(pay_url)
    )

@user_router.callback_query(TopUpProcess.waiting_for_topup_method, F.data == "topup_pay_enot")
async def topup_pay_enot(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Готовлю Enot.io...")
    data = await state.get_data()
    amount = Decimal(str(data.get('topup_amount', 0)))
    if amount <= 0:
        await callback.message.edit_text("❌ Некорректная сумма пополнения.")
        await state.clear()
        return
        
    shop_id = (get_setting("enot_shop_id") or "").strip()
    secret_key = (get_setting("enot_secret_key") or "").strip()
    
    if not shop_id or not secret_key:
        await callback.message.edit_text("❌ Оплата через Enot.io временно недоступна.")
        await state.clear()
        return

    user_id = callback.from_user.id
    payment_id = str(uuid.uuid4())
    metadata = {
        "payment_id": payment_id,
        "user_id": user_id,
        "price": float(amount),
        "action": "top_up",
        "payment_method": "Enot.io",
    }
    try:
        create_pending_transaction(payment_id, user_id, float(amount), metadata)
    except Exception as e:
        logger.warning(f"Enot topup: не удалось создать ожидающую транзакцию: {e}")
        
    pay_url = _build_enot_url(shop_id, secret_key, float(amount), payment_id)
    
    await state.clear()
    await callback.message.edit_text(
        "Нажмите на кнопку ниже для оплаты:",
        reply_markup=keyboards.create_payment_keyboard(pay_url)
    )

def _build_enot_url(shop_id: str, secret_key: str, amount: float, order_id: str) -> str:
    # Enot signature: md5(merchant_id:payment_amount:secret_word:order_id)
    amount_str = f"{amount:.2f}"
    
    raw = f"{shop_id}:{amount_str}:{secret_key}:{order_id}"
    import hashlib
    sign = hashlib.md5(raw.encode('utf-8')).hexdigest()
    
    # https://enot.io/pay/{shop_id}?oa={amount}&o={order_id}&s={sign}
    qs = urlencode({
        "oa": amount_str,
        "o": order_id,
        "s": sign
    })
    return f"https://enot.io/pay/{shop_id}?{qs}"

def get_user_router() -> Router:
    return user_router
