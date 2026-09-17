import { strings as stringsEn } from "./strings.en";
import { stringsRu } from "./strings.ru";

export type Locale = "en" | "ru";
const STORAGE_KEY = "prosthetic-locale";
const uiEn: Record<string, string> = {
  switchLanguage: "Switch language", accountCommunity: "Account and community", close: "Close", navWorkshop: "WORKSHOP", navCommunity: "COMMUNITY", navProfile: "PROFILE", signInRegister: "SIGN IN / REGISTER", signIn: "SIGN IN", signUp: "CREATE ACCOUNT", openConfigurator: "Open the cover configurator", openProfile: "Open your profile", community: "Community", publicDesigns: "Public designs", findDesign: "Find a design by name", search: "SEARCH", loading: "Loading…", rateThis: "Rate this design", noRatings: "No ratings", ratings: "ratings", signInToRate: "Sign in to rate", removeRating: "Remove your rating", rateN: "Rate {n} out of 5", cannotRateOwn: "You cannot rate your own design", saveCurrent: "Save current design", designName: "Design name", saveDesign: "SAVE DESIGN", saving: "Saving…", saved: "Saved ✓", topDesigners: "Top 5 Designers", noRatedDesigners: "No rated designers yet.", yourRank: "Your Rank", signInRank: "Sign in to see your rank.", unableRank: "Unable to load your rank.", noDesigns: "No designs yet.", noRatingsRank: "No ratings yet — rate designs to enter the ranking.", designs: "designs", allDesigns: "All designs", noDesignsFound: "No designs found.", topDesigns: "Top 5 Designs", by: "by", design: "DESIGN", account: "Your account", profileInformation: "Profile information", saveCurrentDesignTitle: "Save current design", noSavedDesigns: "No saved designs yet.", profileSaved: "Profile saved", designSaved: "Design saved", signOut: "SIGN OUT", nickname: "Nickname", email: "Email", password: "Password (8+ characters)", firstName: "First name", lastName: "Last name", city: "City", website: "Website URL", social: "Social profile URL", about: "About you", avatarUrl: "Avatar image URL", yourSettings: "Your settings", saveADesign: "Save a design", loadingProfile: "Loading profile…", profileUnavailable: "Profile unavailable", backConfigurator: "← BACK TO CONFIGURATOR", activity: "Activity", activityAria: "Activity during the last year", action: "action", actions: "actions", changeAvatar: "Change avatar", chooseImage: "Choose an image file", avatarSize: "Image must be 2 MB or smaller", uploading: "Uploading…", uploadSaved: "Saved", noPublished: "No published designs yet.", averageRating: "Average rating", ratingsLabel: "Ratings", websiteLink: "Website", socialLink: "Social profile", error: "Something went wrong.", confirmDelete: "Delete this design?", cancel: "Cancel",
};
const uiRu: Record<string, string> = {
  switchLanguage: "Переключить язык", accountCommunity: "Аккаунт и сообщество", close: "Закрыть", navWorkshop: "МАСТЕРСКАЯ", navCommunity: "СООБЩЕСТВО", navProfile: "ПРОФИЛЬ", signInRegister: "ВОЙТИ / РЕГИСТРАЦИЯ", signIn: "ВОЙТИ", signUp: "СОЗДАТЬ АККАУНТ", openConfigurator: "Открыть конфигуратор оболочки", openProfile: "Открыть профиль", community: "Сообщество", publicDesigns: "Публичные дизайны", findDesign: "Найти дизайн по названию", search: "ИСКАТЬ", loading: "Загрузка…", rateThis: "Оценить дизайн", noRatings: "Нет оценок", ratings: "оценок", signInToRate: "Войдите, чтобы оценить", removeRating: "Убрать вашу оценку", rateN: "Оценить на {n} из 5", cannotRateOwn: "Нельзя оценивать собственный дизайн", saveCurrent: "Сохранить текущий дизайн", designName: "Название дизайна", saveDesign: "СОХРАНИТЬ ДИЗАЙН", saving: "Сохраняем…", saved: "Сохранено ✓", topDesigners: "ТОП-5 ДИЗАЙНЕРОВ", noRatedDesigners: "Оценённых дизайнеров пока нет.", yourRank: "Ваш рейтинг", signInRank: "Войдите, чтобы увидеть своё место.", unableRank: "Не удалось загрузить ваш рейтинг.", noDesigns: "Дизайнов пока нет.", noRatingsRank: "Оценок пока нет — оцените дизайны, чтобы попасть в рейтинг.", designs: "дизайнов", allDesigns: "Все дизайны", noDesignsFound: "Дизайны не найдены.", topDesigns: "ТОП-5 ДИЗАЙНОВ", by: "автор:", design: "ДИЗАЙН", account: "Ваш аккаунт", profileInformation: "Информация профиля", saveCurrentDesignTitle: "Сохранить текущий дизайн", noSavedDesigns: "Сохранённых дизайнов пока нет.", profileSaved: "Профиль сохранён", designSaved: "Дизайн сохранён", signOut: "ВЫЙТИ", nickname: "Никнейм", email: "Почта", password: "Пароль (от 8 символов)", firstName: "Имя", lastName: "Фамилия", city: "Город", website: "Сайт", social: "Ссылка на соцсеть", about: "О себе", avatarUrl: "URL аватарки", yourSettings: "Ваши настройки", saveADesign: "Сохранить дизайн", loadingProfile: "Загрузка профиля…", profileUnavailable: "Профиль недоступен", backConfigurator: "← НАЗАД К КОНФИГУРАТОРУ", activity: "Активность", activityAria: "Активность за последний год", action: "действие", actions: "действий", changeAvatar: "Изменить аватарку", chooseImage: "Выберите файл изображения", avatarSize: "Изображение должно быть не больше 2 МБ", uploading: "Загрузка…", uploadSaved: "Сохранено", noPublished: "Опубликованных дизайнов пока нет.", averageRating: "Средняя оценка", ratingsLabel: "Оценки", websiteLink: "Сайт", socialLink: "Соцсеть", error: "Что-то пошло не так.", confirmDelete: "Удалить этот дизайн?", cancel: "Отмена",
};

uiEn.saveProfile = "SAVE PROFILE";
uiRu.saveProfile = "РЎРћРҐР РђРќРРўР¬ РџР РћР¤РР›Р¬";
uiEn.delete = "DELETE";
uiRu.delete = "РЈР”РђР›РРўР¬";
uiEn.less = "Less";
uiRu.less = "РњРµРЅСЊС€Рµ";
uiEn.more = "More";
uiRu.more = "Р‘РѕР»СЊС€Рµ";

function repairMojibake(value: string): string {
  if (!/[РС]Р|вЂ|вњ/.test(value)) return value;
  const extension = "\u0402\u0403\u201a\u0453\u201e\u2026\u2020\u2021\u20ac\u2030\u0409\u2039\u040a\u040c\u040b\u040f\u0452\u2018\u2019\u201c\u201d\u2022\u2013\u2014\u0098\u2122\u0459\u203a\u045a\u045c\u045b\u045f\u00a0\u040e\u045e\u0408\u00a4\u0490\u00a6\u00a7\u0401\u00a9\u0404\u00ab\u00ac\u00ad\u00ae\u0407\u00b0\u00b1\u0406\u0456\u0491\u00b5\u00b6\u00b7\u0451\u2116\u0454\u00bb\u0458\u0405\u0455\u0457\u00b9\u0453\u0452\u00bc\u00bd\u045a\u045c\u045b\u045f";
  const bytes = Array.from(value, (char) => {
    const code = char.codePointAt(0) ?? 0;
    if (code >= 0x0410 && code <= 0x042f) return code - 0x0350;
    if (code >= 0x0430 && code <= 0x044f) return code - 0x0340;
    const position = extension.indexOf(char);
    return position >= 0 ? 0x80 + position : code <= 0xff ? code : 0x3f;
  });
  try { return new TextDecoder().decode(Uint8Array.from(bytes)); } catch { return value; }
}

export let locale: Locale = readLocale();
export let strings: typeof stringsEn = locale === "ru" ? stringsRu : stringsEn;
const listeners = new Set<() => void>();

function readLocale(): Locale {
  try { return localStorage.getItem(STORAGE_KEY) === "ru" ? "ru" : "en"; } catch { return "en"; }
}
export function t(key: string, vars: Record<string, string | number> = {}): string {
  const value = (locale === "ru" ? uiRu[key] : undefined) ?? uiEn[key] ?? key;
  const repaired = repairMojibake(value);
  return Object.entries(vars).reduce((text, [name, replacement]) => text.replaceAll(`{${name}}`, String(replacement)), repaired);
}
export function setLocale(next: Locale): void {
  if (next === locale) return;
  locale = next;
  strings = next === "ru" ? stringsRu : stringsEn;
  try { localStorage.setItem(STORAGE_KEY, next); } catch { /* storage may be disabled */ }
  listeners.forEach((listener) => listener());
}
export function subscribe(listener: () => void): () => void { listeners.add(listener); return () => listeners.delete(listener); }
