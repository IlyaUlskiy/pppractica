// Модуль: main.js
// Назначение: Клиентская логика (анимации, авто-закрытие алертов, валидация форм)
document.addEventListener('DOMContentLoaded', function() {
    // 1. Автоматическое скрытие флеш-сообщений через 5 секунд
    const alerts = document.querySelectorAll('.flash');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.opacity = '0';
            setTimeout(() => alert.remove(), 300); // Удаляем из DOM после анимации
        }, 5000);
    });

    // 2. Подсветка активного пункта меню
    const currentPath = window.location.pathname;
    document.querySelectorAll('.nav-link').forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });

    // 3. Простая валидация телефонов (визуальная)
    const phoneInput = document.querySelector('input[name="phone"]');
    if (phoneInput) {
        phoneInput.addEventListener('input', function(e) {
            let val = e.target.value.replace(/\D/g, '');
            if (val.length > 0) {
                if (val[0] === '7' || val[0] === '8') val = val.substring(1);
                let formatted = '+7';
                if (val.length > 0) formatted += ' (' + val.substring(0, 3);
                if (val.length >= 3) formatted += ') ' + val.substring(3, 6);
                if (val.length >= 6) formatted += '-' + val.substring(6, 8);
                if (val.length >= 8) formatted += '-' + val.substring(8, 10);
                e.target.value = formatted;
            }
        });
    }
});