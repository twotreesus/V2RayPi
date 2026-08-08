(function (window, document) {
    var STORAGE_KEY = "v2raypi_language";
    var messages = {};
    var listeners = [];

    function initialLanguage() {
        var saved = null;
        try {
            saved = window.localStorage.getItem(STORAGE_KEY);
        } catch (error) {
            saved = null;
        }
        if (saved === "zh" || saved === "en") {
            return saved;
        }
        return (window.navigator.language || "").toLowerCase().startsWith("zh")
            ? "zh"
            : "en";
    }

    var language = initialLanguage();

    function interpolate(text, params) {
        return Object.keys(params || {}).reduce(function (result, key) {
            return result.replace(
                new RegExp("\\{" + key + "\\}", "g"),
                String(params[key])
            );
        }, text);
    }

    function translation(key, params) {
        var entry = messages[key];
        if (!entry) {
            return key;
        }
        return interpolate(entry[language] || entry.zh || key, params);
    }

    function apply(root) {
        var target = root || document;
        target.querySelectorAll("[data-i18n]").forEach(function (element) {
            element.textContent = translation(element.dataset.i18n);
        });
        target.querySelectorAll("[data-i18n-html]").forEach(function (element) {
            element.innerHTML = translation(element.dataset.i18nHtml);
        });
        target.querySelectorAll("[data-i18n-title]").forEach(function (element) {
            element.setAttribute(
                "title",
                translation(element.dataset.i18nTitle)
            );
        });
        target.querySelectorAll("[data-i18n-placeholder]").forEach(function (element) {
            element.setAttribute(
                "placeholder",
                translation(element.dataset.i18nPlaceholder)
            );
        });
        target.querySelectorAll("[data-i18n-tooltip]").forEach(function (element) {
            element.setAttribute(
                "mdui-tooltip",
                JSON.stringify({
                    content: translation(element.dataset.i18nTooltip),
                })
            );
        });
        document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
        var buttonLabel = document.getElementById("language_label");
        if (buttonLabel) {
            buttonLabel.textContent = language === "zh" ? "中" : "EN";
        }
    }

    function setLanguage(nextLanguage) {
        if (nextLanguage !== "zh" && nextLanguage !== "en") {
            return;
        }
        language = nextLanguage;
        try {
            window.localStorage.setItem(STORAGE_KEY, language);
        } catch (error) {
            // Language switching still works for the current page.
        }
        apply(document);
        listeners.forEach(function (listener) {
            listener(language);
        });
    }

    window.I18n = {
        register: function (entries) {
            Object.keys(entries).forEach(function (key) {
                messages[key] = entries[key];
            });
        },
        t: translation,
        apiError: function (data, fallbackKey) {
            var key = data && data.error ? "error." + data.error : fallbackKey;
            return translation(key || "error.generic");
        },
        apply: apply,
        language: function () {
            return language;
        },
        toggle: function () {
            setLanguage(language === "zh" ? "en" : "zh");
        },
        onChange: function (listener) {
            listeners.push(listener);
        },
    };
    window.t = translation;
})(window, document);
