/**
 * Wiring.
 *
 * Dragging a slider asks for a draft mesh; letting go asks for the real one.
 * Requests are debounced and the newest always wins, so the model on screen is
 * the model the panel describes.
 */

import {
  downloadCover,
  fetchProfile,
  fetchCover,
  fetchSchema,
  login,
  readMotif,
  uploadMotif,
  currentUser,
  communityDesign,
  communityDesigns,
  loadDesign,
  removeDesign,
  saveDesign,
  myRank,
  rateDesign,
  register,
  type SavedDesign,
  signOut,
  uploadAvatar,
  updateProfile,
  type PublicProfile,
  type RankedDesign,
  type RankedDesigner,
  type User,
  topDesigners,
  topDesigns,
  type Params,
  type PresetSpec,
  type Schema,
  type Silhouette,
} from "./api";
import { Panel } from "./panel";
import { has } from "./strings.en";
import { locale, setLocale, strings, subscribe, t } from "./i18n";
import { Viewer } from "./viewer";

const DEBOUNCE_MS = 250;

const stage = document.getElementById("stage") as HTMLCanvasElement;
const masthead = document.getElementById("masthead") as HTMLElement;
const panelRoot = document.getElementById("panel") as HTMLElement;
const headerActions = document.createElement("nav");
headerActions.className = "header-actions";
headerActions.setAttribute("aria-label", t("accountCommunity"));
masthead.prepend(headerActions);

let schema: Schema;
let params: Params;
let panel: Panel;
let viewer: Viewer;
let specLine: HTMLElement | null = null;

let timer: number | undefined;
let inflight: AbortController | null = null;
let pending = false;

/** The picture the session is holding, as the server read it. */
let silhouette: Silhouette | null = null;
let motifTimer: number | undefined;
let user: User | null = null;
let accountDialog: HTMLElement;
let designList: HTMLElement;
let communityDialog: HTMLElement;
let communityList: HTMLElement;
let workshopSaveArea: HTMLElement;
let workshopRatingArea: HTMLElement;
let workshopBottomBar: HTMLElement;
let profilePage: HTMLElement;
let authButton: HTMLButtonElement;
let profileNavButton: HTMLButtonElement;
let languageButton: HTMLButtonElement;
let activeWorkshopDesign: SavedDesign | null = null;

/** The three controls that change how a held picture is read. */
const READING = new Set(["threshold_bias", "motif_smoothing", "motif_invert"]);

/** Ink or paper, whichever stays readable on the chosen colour. */
function readableOn(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  const channel = (v: number) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const luminance =
    0.2126 * channel((n >> 16) & 255) +
    0.7152 * channel((n >> 8) & 255) +
    0.0722 * channel(n & 255);
  return luminance > 0.35 ? "#1a1c1b" : "#e9eae6";
}

function applyAccent(hex: string): void {
  document.documentElement.style.setProperty("--accent", hex);
  document.documentElement.style.setProperty("--accent-ink", readableOn(hex));
}

function escapeHtml(value: string): string {
  const entities: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" };
  return value.replace(/[&<>'"]/g, (char) => entities[char] ?? char);
}

function miniAvatar(person: { nickname: string; avatar_url?: string }): HTMLElement {
  const avatar = document.createElement("span"); avatar.className = "header-avatar";
  const fallback = document.createElement("span"); fallback.textContent = person.nickname.slice(0, 2).toUpperCase(); avatar.append(fallback);
  if (person.avatar_url) {
    const image = document.createElement("img"); image.src = person.avatar_url.startsWith("/api/") ? `${person.avatar_url}?v=${Date.now()}` : person.avatar_url; image.alt = "";
    image.addEventListener("load", () => fallback.hidden = true);
    image.addEventListener("error", () => image.remove());
    avatar.append(image);
  }
  return avatar;
}

function accountUi(): void {
  const button = document.createElement("button");
  button.className = "auth-button";
  button.type = "button";
  button.textContent = t("signInRegister");
  button.onclick = () => accountDialog.hidden = false;
  authButton = button;
  headerActions.append(button);

  accountDialog = document.createElement("section");
  accountDialog.className = "account-dialog";
  accountDialog.hidden = true;
  accountDialog.innerHTML = `<div class="account-card"><button class="account-close" type="button" aria-label="Close">×</button><p class="group">Personal cabinet</p><h2 class="account-title">Your designs</h2><div class="account-content"></div></div>`;
  document.body.append(accountDialog);
  (accountDialog.querySelector(".account-close") as HTMLElement).setAttribute("aria-label", t("close"));
  (accountDialog.querySelector(".group") as HTMLElement).textContent = t("account");
  (accountDialog.querySelector(".account-title") as HTMLElement).textContent = t("designs");
  accountDialog.querySelector(".account-close")!.addEventListener("click", () => accountDialog.hidden = true);
  designList = accountDialog.querySelector(".account-content") as HTMLElement;
}

function communityUi(): void {
  const button = document.createElement("button");
  button.className = "community-button";
  button.type = "button";
  button.textContent = t("navCommunity");
  button.addEventListener("click", () => { communityDialog.hidden = false; void renderCommunity(); });
  headerActions.append(button);

  communityDialog = document.createElement("section");
  communityDialog.className = "account-dialog community-dialog";
  communityDialog.hidden = true;
  communityDialog.innerHTML = `<div class="account-card community-card"><button class="account-close" type="button" aria-label="Close">×</button><p class="group">Community</p><h2 class="account-title">Public designs</h2><form class="community-search"><input name="search" placeholder="Find a design by name" /><button type="submit">SEARCH</button></form><div class="community-content"></div></div>`;
  document.body.append(communityDialog);
  (communityDialog.querySelector(".account-close") as HTMLElement).setAttribute("aria-label", t("close"));
  (communityDialog.querySelector(".group") as HTMLElement).textContent = t("community");
  (communityDialog.querySelector(".account-title") as HTMLElement).textContent = t("publicDesigns");
  (communityDialog.querySelector("[name=search]") as HTMLInputElement).placeholder = t("findDesign");
  (communityDialog.querySelector(".community-search button") as HTMLElement).textContent = t("search");
  communityDialog.querySelector(".account-close")!.addEventListener("click", () => communityDialog.hidden = true);
  communityList = communityDialog.querySelector(".community-content") as HTMLElement;
  communityDialog.querySelector(".community-search")!.addEventListener("submit", (event) => { event.preventDefault(); void renderCommunity(new FormData(event.currentTarget as HTMLFormElement).get("search") as string); });
}

function navigationUi(): void {
  const workshop = document.createElement("button");
  workshop.className = "workshop-button";
  workshop.type = "button";
  workshop.textContent = t("navWorkshop");
  workshop.title = t("openConfigurator");
  workshop.addEventListener("click", navigateWorkshop);
  headerActions.prepend(workshop);

  const profile = document.createElement("button");
  profile.className = "profile-button";
  profile.type = "button";
  profile.textContent = t("navProfile");
  profile.title = t("openProfile");
  profileNavButton = profile;
  profile.onclick = () => {
    if (user) navigateProfile(user.id);
    else accountDialog.hidden = false;
  };
  headerActions.append(profile);
}

function languageUi(): void {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "language-switch";
  button.innerHTML = `<span data-locale="en">EN</span><span aria-hidden="true">/</span><span data-locale="ru">RU</span>`;
  button.addEventListener("click", () => setLocale(locale === "en" ? "ru" : "en"));
  languageButton = button;
  headerActions.append(button);
  updateLanguageButton();
}

function updateLanguageButton(): void {
  if (!languageButton) return;
  languageButton.title = t("switchLanguage");
  languageButton.setAttribute("aria-label", t("switchLanguage"));
  languageButton.querySelectorAll<HTMLElement>("[data-locale]").forEach((item) => item.classList.toggle("active", item.dataset.locale === locale));
}

function promptSignIn(): void {
  accountDialog.hidden = false;
  void renderAccount(authButton);
}

function refreshRatingSurfaces(): void {
  if (!communityDialog.hidden) {
    const search = (communityDialog.querySelector("[name=search]") as HTMLInputElement).value;
    void renderCommunity(search);
  }
}

function ratingWidget(design: SavedDesign, ownerId?: number): HTMLElement {
  const rating = document.createElement("div"); rating.className = "community-rating workshop-rating";
  const summary = document.createElement("span");
  const stars = document.createElement("span"); stars.className = "rating-stars";
  const buttons: HTMLButtonElement[] = [];
  const isOwner = Boolean(user && ((ownerId !== undefined && ownerId === user.id) || design.user_id === user.id));
  const paintStars = (value: number) => buttons.forEach((button, index) => button.classList.toggle("rating-star-on", index < value));
  const updateSummary = () => {
    const current = design.rating;
    summary.textContent = current?.count ? `${current.average.toFixed(1)} ★ / 5 · ${current.count} ${t("ratings")}` : t("noRatings");
    paintStars(current?.mine ?? 0);
  };
  const restoreStars = () => paintStars(design.rating?.mine ?? 0);
  const ratingTitle = isOwner ? t("cannotRateOwn") : t("rateThis");
  rating.title = ratingTitle;
  stars.title = ratingTitle;
  stars.addEventListener("mouseleave", restoreStars);
  stars.addEventListener("focusout", restoreStars);
  for (let score = 1; score <= 5; score += 1) {
    const star = document.createElement("button");
    star.type = "button";
    star.className = "rating-star";
    star.textContent = "★";
    star.title = isOwner ? ratingTitle : design.rating?.mine === score ? t("removeRating") : t("rateN", { n: score });
    star.setAttribute("aria-label", star.title);
    star.disabled = isOwner;
    star.classList.toggle("rating-star-on", score <= (design.rating?.mine ?? 0));
    star.addEventListener("mouseenter", () => paintStars(score));
    star.addEventListener("focus", () => paintStars(score));
    star.addEventListener("click", async (event) => {
      event.stopPropagation();
      if (isOwner) return;
      if (!user) { summary.textContent = t("signInToRate"); promptSignIn(); return; }
      const nextScore = design.rating?.mine === score ? 0 : score;
      try {
        design.rating = await rateDesign(design.id, nextScore);
        updateSummary();
        refreshRatingSurfaces();
      } catch (error) { summary.textContent = (error as Error).message; }
    });
    buttons.push(star);
    stars.append(star);
  }
  rating.append(summary, stars);
  updateSummary();
  return rating;
}

function renderWorkshopSave(): void {
  if (!workshopSaveArea) return;
  workshopSaveArea.replaceChildren();
  workshopSaveArea.hidden = !user;
  if (!user) return;

  const form = document.createElement("form"); form.className = "workshop-save-form";
  const name = document.createElement("input"); name.name = "name"; name.value = "My cover"; name.maxLength = 100; name.placeholder = t("designName");
  const button = document.createElement("button"); button.type = "submit"; button.textContent = t("saveDesign");
  const message = document.createElement("p"); message.className = "workshop-save-message";
  form.append(name, button, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    message.textContent = t("saving");
    try {
      await saveDesign(String(new FormData(form).get("name")), params);
      button.disabled = false;
      message.textContent = t("saved");
    } catch (error) {
      button.disabled = false;
      message.textContent = (error as Error).message;
    }
  });
  const heading = document.createElement("p"); heading.className = "group"; heading.textContent = t("saveCurrent");
  workshopSaveArea.append(heading, form);
}

function renderWorkshopRating(design: SavedDesign | null): void {
  if (!workshopRatingArea) return;
  workshopRatingArea.replaceChildren();
  const isOwnDesign = Boolean(design && user && design.user_id === user.id);
  workshopRatingArea.hidden = !design || isOwnDesign;
  if (!design || isOwnDesign) return;
  const heading = document.createElement("p"); heading.className = "group"; heading.textContent = t("rateThis");
  workshopRatingArea.append(heading, ratingWidget(design, design.user_id));
}

function sectionHeading(text: string): HTMLElement {
  const heading = document.createElement("h3"); heading.className = "community-section-title"; heading.textContent = text; return heading;
}

function rankedDesignerRow(designer: RankedDesigner, position: number | null): HTMLElement {
  const row = document.createElement("article"); row.className = "community-ranked-row";
  row.tabIndex = 0;
  const open = () => navigateProfile(designer.id);
  row.addEventListener("click", open);
  row.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
  const place = document.createElement("strong"); place.className = "community-rank-place"; place.textContent = position ? `#${position}` : "—";
  const avatar = miniAvatar(designer);
  const identity = document.createElement("div"); identity.className = "community-ranked-identity";
  const nickname = document.createElement("strong"); nickname.textContent = designer.nickname;
  const details = document.createElement("span"); details.textContent = `${designer.designs} designs · ${designer.ratings} ratings`;
  identity.append(nickname, details);
  details.textContent = `${designer.designs} ${t("designs")} · ${designer.ratings} ${t("ratings")}`;
  const score = document.createElement("span"); score.className = "community-ranked-score";
  score.textContent = `★ ${designer.average.toFixed(1)} / 5`;
  row.append(place, avatar, identity, score); return row;
}

function rankedDesignCard(design: RankedDesign): HTMLElement {
  const card = document.createElement("article"); card.className = "community-top-design";
  card.addEventListener("click", () => void openCommunityDesign(design.id));
  const name = document.createElement("strong"); name.className = "community-top-design-name"; name.textContent = design.name;
  const author = document.createElement("button"); author.type = "button"; author.className = "community-top-design-author";
  author.replaceChildren(miniAvatar(design), document.createTextNode(`${t("by")} ${design.nickname}`));
  author.addEventListener("click", (event) => { event.stopPropagation(); navigateProfile(design.user_id); });
  const rating = document.createElement("span"); rating.className = "community-top-design-rating";
  rating.textContent = `★ ${design.average.toFixed(1)} / 5 · ${design.ratings} ${t("ratings")}`;
  card.append(name, author, rating); return card;
}

async function renderCommunity(search = ""): Promise<void> {
  communityList.replaceChildren(document.createTextNode(t("loading")));
  try {
    const rankRequest = user ? myRank().catch(() => null) : Promise.resolve(null);
    const [designs, designers, topDesignList, rank] = await Promise.all([
      communityDesigns(search),
      topDesigners(5),
      topDesigns(5),
      rankRequest,
    ]);
    communityList.replaceChildren();

    const topSection = document.createElement("section"); topSection.className = "community-ranking-section"; topSection.append(sectionHeading(t("topDesigners")));
    if (!designers.length) {
      topSection.append(Object.assign(document.createElement("p"), { className: "community-empty", textContent: t("noRatedDesigners") }));
    } else {
      const list = document.createElement("div"); list.className = "community-ranked-list";
      designers.forEach((designer, index) => list.append(rankedDesignerRow(designer, index + 1)));
      topSection.append(list);
    }
    communityList.append(topSection);

    const rankSection = document.createElement("section"); rankSection.className = "community-ranking-section community-your-rank"; rankSection.append(sectionHeading("Your Rank"));
    if (!user) {
      rankSection.append(Object.assign(document.createElement("p"), { className: "community-empty", textContent: "Sign in to see your rank." }));
    } else if (!rank) {
      rankSection.append(Object.assign(document.createElement("p"), { className: "community-empty", textContent: "Unable to load your rank." }));
    } else {
      rankSection.append(rankedDesignerRow(rank.designer, rank.rank ?? 0));
      const note = document.createElement("p"); note.className = "community-rank-note";
      note.textContent = rank.designer.designs === 0 ? "No designs yet." : rank.rank === null ? "No ratings yet — rate designs to enter the ranking." : "";
      note.textContent = rank.designer.designs === 0 ? t("noDesigns") : rank.rank === null ? t("noRatingsRank") : "";
      if (note.textContent) rankSection.append(note);
    }
    communityList.append(rankSection);

    const designsSection = document.createElement("section"); designsSection.className = "community-ranking-section"; designsSection.append(sectionHeading(t("topDesigns")));
    if (!topDesignList.length) {
      designsSection.append(Object.assign(document.createElement("p"), { className: "community-empty", textContent: t("noRatedDesigners") }));
    } else {
      const list = document.createElement("div"); list.className = "community-top-designs";
      topDesignList.forEach((design) => list.append(rankedDesignCard(design)));
      designsSection.append(list);
    }
    communityList.append(designsSection);

    const heading = document.createElement("p"); heading.className = "group community-design-heading"; heading.textContent = search ? `${t("allDesigns")}: "${search}"` : t("allDesigns"); communityList.append(heading);
    if (!designs.length) { const empty = document.createElement("p"); empty.className = "community-empty"; empty.textContent = t("noDesignsFound"); communityList.append(empty); }
    for (const design of designs) communityList.append(communityDesignRow(design));
  } catch (error) { communityList.textContent = (error as Error).message; }
}

function communityDesignRow(design: SavedDesign): HTMLElement {
  const row = document.createElement("article"); row.className = "community-design";
  row.addEventListener("click", () => void openCommunityDesign(design.id));
  const title = document.createElement("button"); title.className = "community-design-title"; title.type = "button"; title.textContent = design.name;
  title.addEventListener("click", (event) => { event.stopPropagation(); void openCommunityDesign(design.id); });
  const owner = document.createElement("button"); owner.className = "community-owner profile-link"; owner.type = "button"; owner.textContent = `${t("by")} ${design.nickname ?? t("design")}`;
  if (design.user_id) owner.addEventListener("click", (event) => { event.stopPropagation(); navigateProfile(design.user_id!); });
  row.append(title, owner, ratingWidget(design, design.user_id)); return row;
}

async function renderAccount(button: HTMLButtonElement): Promise<void> {
  if (Boolean(user)) {
    const current = user;
    if (!current) return;
    button.hidden = false;
    button.className = "auth-button auth-user-button";
    button.onclick = () => navigateProfile(current.id);
    profileNavButton.hidden = true;
    accountDialog.hidden = true;
    try {
      const own = await fetchProfile(current.id);
      button.replaceChildren(miniAvatar(own.user), Object.assign(document.createElement("span"), { textContent: own.user.nickname }));
    } catch {
      button.replaceChildren(Object.assign(document.createElement("span"), { textContent: current.nickname }));
    }
    renderWorkshopSave();
    return;
  }
  button.hidden = false;
  button.className = "auth-button";
  button.onclick = () => accountDialog.hidden = false;
  profileNavButton.hidden = false;
  button.textContent = t("signInRegister");
  renderWorkshopSave();
  const title = accountDialog.querySelector(".account-title") as HTMLElement;
  if (!user) {
    title.textContent = t("account");
    designList.innerHTML = `<div class="auth-tabs"><button type="button" class="auth-tab auth-tab-on" data-mode="login">${t("signIn")}</button><button type="button" class="auth-tab" data-mode="register">${t("signUp")}</button></div><div class="auth-form-host"></div>`;
    const host = designList.querySelector(".auth-form-host") as HTMLElement;
    const show = (mode: "login" | "register") => {
      for (const tab of designList.querySelectorAll(".auth-tab")) tab.classList.toggle("auth-tab-on", (tab as HTMLElement).dataset.mode === mode);
      host.innerHTML = `<form class="account-form">${mode === "register" ? `<input name="nickname" placeholder="${t("nickname")}" minlength="2" maxlength="24" pattern="[A-Za-z0-9_-]+" required />` : ""}<input name="email" type="email" placeholder="${t("email")}" required /><input name="password" type="password" placeholder="${t("password")}" minlength="8" required /><button class="auth-submit" type="submit">${mode === "register" ? t("signUp") : t("signIn")}</button><p class="account-message"></p></form>`;
      const form = host.querySelector("form") as HTMLFormElement;
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = new FormData(form);
        const message = form.querySelector(".account-message") as HTMLElement;
        try {
          user = mode === "register"
            ? await register(String(data.get("email")), String(data.get("password")), String(data.get("nickname")))
            : await login(String(data.get("email")), String(data.get("password")));
          await renderAccount(button);
        } catch (error) { message.textContent = (error as Error).message; }
      });
    };
    for (const tab of designList.querySelectorAll(".auth-tab")) tab.addEventListener("click", () => show((tab as HTMLElement).dataset.mode as "login" | "register"));
    show("login");
    return;
  }
  title.textContent = t("account");
  const own = await fetchProfile(user.id);
  const details = own.user;
  designList.innerHTML = `<div class="account-toolbar"><button class="profile-link own-profile" type="button">@${escapeHtml(user.nickname)}</button><span>${escapeHtml(user.email)}</span><button class="sign-out" type="button">${t("signOut")}</button></div><p class="group">${t("profileInformation")}</p><form class="profile-form"><div class="profile-fields"><input name="avatar_url" type="url" placeholder="${t("avatarUrl")}" value="${escapeHtml(details.avatar_url)}" /><input name="first_name" placeholder="${t("firstName")}" maxlength="60" value="${escapeHtml(details.first_name)}" /><input name="last_name" placeholder="${t("lastName")}" maxlength="60" value="${escapeHtml(details.last_name)}" /><input name="city" placeholder="${t("city")}" maxlength="100" value="${escapeHtml(details.city)}" /><input name="website" type="url" placeholder="${t("website")}" value="${escapeHtml(details.website)}" /><input name="social_link" type="url" placeholder="${t("social")}" value="${escapeHtml(details.social_link)}" /></div><textarea name="bio" maxlength="1000" placeholder="${t("about")}">${escapeHtml(details.bio)}</textarea><button type="submit">${t("saveProfile")}</button></form><p class="profile-message"></p><p class="group">${t("saveCurrentDesignTitle")}</p><form class="save-form"><input name="name" value="My cover" maxlength="100" placeholder="${t("designName")}" /><button type="submit">${t("saveDesign")}</button></form><p class="account-message"></p><div class="design-items"></div>`;
  const message = designList.querySelector(".account-message") as HTMLElement;
  const items = designList.querySelector(".design-items") as HTMLElement;
  const designs = own.designs;
  for (const design of designs) {
    const item = document.createElement("div"); item.className = "design-item";
    const load = document.createElement("button"); load.className = "design-load"; load.type = "button"; load.textContent = design.name;
    load.addEventListener("click", () => void openDesign(design.id));
    const del = document.createElement("button"); del.className = "design-delete"; del.type = "button"; del.textContent = "×"; del.title = "Delete design";
    del.addEventListener("click", async () => { await removeDesign(design.id); void renderAccount(button); });
    item.append(load, del); items.append(item);
  }
  if (!designs.length) items.textContent = t("noSavedDesigns");
  designList.querySelector(".own-profile")!.addEventListener("click", () => navigateProfile(user!.id));
  designList.querySelector(".profile-form")!.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const data = new FormData(form);
    const profileMessage = designList.querySelector(".profile-message") as HTMLElement;
    try {
      await updateProfile({
        avatar_url: String(data.get("avatar_url")),
        first_name: String(data.get("first_name")),
        last_name: String(data.get("last_name")),
        city: String(data.get("city")),
        bio: String(data.get("bio")),
        website: String(data.get("website")),
        social_link: String(data.get("social_link")),
      });
      profileMessage.textContent = t("profileSaved");
    } catch (error) { profileMessage.textContent = (error as Error).message; }
  });
  designList.querySelector(".save-form")!.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget as HTMLFormElement).get("name"));
    try { await saveDesign(name, params); message.textContent = t("designSaved"); void renderAccount(button); }
    catch (error) { message.textContent = (error as Error).message; }
  });
  designList.querySelector(".sign-out")!.addEventListener("click", async () => { await signOut(); user = null; void renderAccount(button); route(); });
}

async function openDesign(id: number): Promise<void> {
  const design = await loadDesign(id);
  activeWorkshopDesign = null;
  renderWorkshopRating(null);
  params = { ...design.params };
  silhouette = null;
  if (params.hole_shape === "image" && params.motif_id) {
    try { silhouette = await readMotif(params); } catch { /* preview will remain empty */ }
  }
  panel.setSilhouette(silhouette, silhouette ? noteFor(silhouette) : "");
  refreshPanel(); request(false); accountDialog.hidden = true;
}

async function openCommunityDesign(id: number): Promise<void> {
  const design = await communityDesign(id);
  activeWorkshopDesign = design;
  renderWorkshopRating(design);
  params = { ...design.params };
  silhouette = null;
  if (params.hole_shape === "image" && params.motif_id) {
    try { silhouette = await readMotif(params); } catch { /* preview will remain empty */ }
  }
  panel.setSilhouette(silhouette, silhouette ? noteFor(silhouette) : "");
  refreshPanel(); request(false); communityDialog.hidden = true;
}

function profileUi(): void {
  profilePage = document.createElement("main");
  profilePage.className = "profile-page";
  profilePage.hidden = true;
  document.body.append(profilePage);
  window.addEventListener("popstate", () => void route());
}

function navigateProfile(id: number): void {
  accountDialog.hidden = true;
  communityDialog.hidden = true;
  window.history.pushState({}, "", `/profile/${id}`);
  void route();
}

function showConfigurator(): void {
  document.body.classList.remove("profile-open");
  profilePage.hidden = true;
}

function navigateWorkshop(): void {
  accountDialog.hidden = true;
  communityDialog.hidden = true;
  window.history.pushState({}, "", "/workshop");
  showConfigurator();
}

function leaveProfile(): void {
  navigateWorkshop();
}

async function route(): Promise<void> {
  const match = window.location.pathname.match(/^\/profile\/(\d+)\/?$/);
  if (match) {
    document.body.classList.add("profile-open");
    profilePage.hidden = false;
    await renderProfile(Number(match[1]));
    return;
  }
  if (window.location.pathname === "/" || window.location.pathname === "") {
    window.history.replaceState({}, "", "/workshop");
  }
  showConfigurator();
}

function avatarFor(person: PublicProfile["user"], editable = false, onFile?: (file: File, status: HTMLElement) => void): HTMLElement {
  const wrap = document.createElement(editable ? "button" : "div"); wrap.className = "profile-avatar";
  if (editable) {
    (wrap as HTMLButtonElement).type = "button";
    wrap.setAttribute("aria-label", t("changeAvatar"));
    wrap.title = t("changeAvatar");
  }
  const fallback = document.createElement("span"); fallback.textContent = person.nickname.slice(0, 2).toUpperCase(); wrap.append(fallback);
  if (person.avatar_url) {
    const image = document.createElement("img"); image.src = person.avatar_url.startsWith("/api/") ? `${person.avatar_url}?v=${Date.now()}` : person.avatar_url; image.alt = `${person.nickname} avatar`;
    image.addEventListener("load", () => fallback.hidden = true);
    image.addEventListener("error", () => image.remove());
    wrap.append(image);
  }
  if (editable && onFile) {
    const status = document.createElement("span"); status.className = "avatar-status"; wrap.append(status);
    const input = document.createElement("input"); input.type = "file"; input.accept = "image/*"; input.hidden = true;
    wrap.addEventListener("click", () => input.click());
    input.addEventListener("click", (event) => event.stopPropagation());
    input.addEventListener("change", () => {
      const file = input.files?.[0];
      if (!file) return;
      if (!file.type.startsWith("image/")) { status.textContent = t("chooseImage"); return; }
      if (file.size > 2 * 1024 * 1024) { status.textContent = t("avatarSize"); return; }
      const preview = document.createElement("img"); preview.src = URL.createObjectURL(file); preview.alt = `${person.nickname} avatar preview`;
      wrap.querySelectorAll("img").forEach((image) => image.remove());
      fallback.hidden = true; wrap.append(preview, status, input); status.textContent = t("uploading");
      onFile(file, status);
    });
    wrap.append(input);
  }
  return wrap;
}

function activityHeatmap(data: PublicProfile["activity"]): HTMLElement {
  const section = document.createElement("section"); section.className = "profile-section";
  const title = document.createElement("h2"); title.textContent = t("activity"); section.append(title);
  const counts = new Map(data.map((day) => [day.date, day.count]));
  const max = Math.max(1, ...data.map((day) => day.count));
  const grid = document.createElement("div"); grid.className = "activity-grid"; grid.setAttribute("aria-label", t("activityAria"));
  const end = new Date(); end.setHours(0, 0, 0, 0);
  const start = new Date(end); start.setDate(start.getDate() - 364 - start.getDay());
  for (const day = new Date(start); day <= end; day.setDate(day.getDate() + 1)) {
    const key = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
    const count = counts.get(key) ?? 0;
    const cell = document.createElement("span"); cell.className = "activity-day";
    cell.dataset.level = count ? String(Math.max(1, Math.ceil((count / max) * 4))) : "0";
    cell.title = `${key}: ${count} ${count === 1 ? t("action") : t("actions")}`;
    grid.append(cell);
  }
  const legend = document.createElement("div"); legend.className = "activity-legend"; legend.append(document.createTextNode(t("less")));
  for (let level = 0; level <= 4; level += 1) { const cell = document.createElement("span"); cell.className = "activity-day"; cell.dataset.level = String(level); legend.append(cell); }
  legend.append(document.createTextNode(t("more"))); section.append(grid, legend); return section;
}

function ownerProfileTools(data: PublicProfile): HTMLElement {
  const section = document.createElement("section"); section.className = "profile-owner-tools";
  const heading = document.createElement("h2"); heading.textContent = t("yourSettings"); section.append(heading);
  const form = document.createElement("form"); form.className = "profile-form";
  const avatarUrl = data.user.avatar_url.startsWith("/api/") ? "" : data.user.avatar_url;
  form.innerHTML = `<div class="profile-fields"><input name="avatar_url" type="url" placeholder="${t("avatarUrl")}" value="${escapeHtml(avatarUrl)}" /><input name="first_name" placeholder="${t("firstName")}" maxlength="60" value="${escapeHtml(data.user.first_name)}" /><input name="last_name" placeholder="${t("lastName")}" maxlength="60" value="${escapeHtml(data.user.last_name)}" /><input name="city" placeholder="${t("city")}" maxlength="100" value="${escapeHtml(data.user.city)}" /><input name="website" type="url" placeholder="${t("website")}" value="${escapeHtml(data.user.website)}" /><input name="social_link" type="url" placeholder="${t("social")}" value="${escapeHtml(data.user.social_link)}" /></div><textarea name="bio" maxlength="1000" placeholder="${t("about")}">${escapeHtml(data.user.bio)}</textarea><button type="submit">${t("saveProfile")}</button><p class="profile-message"></p>`;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = new FormData(form);
    const message = form.querySelector(".profile-message") as HTMLElement;
    try {
      await updateProfile({
        avatar_url: String(values.get("avatar_url")),
        first_name: String(values.get("first_name")),
        last_name: String(values.get("last_name")),
        city: String(values.get("city")),
        bio: String(values.get("bio")),
        website: String(values.get("website")),
        social_link: String(values.get("social_link")),
      });
      message.textContent = t("profileSaved");
      await renderProfile(data.user.id);
    } catch (error) { message.textContent = (error as Error).message; }
  });
  section.append(form);

  const saveHeading = document.createElement("h2"); saveHeading.textContent = t("saveADesign"); section.append(saveHeading);
  const save = document.createElement("form"); save.className = "save-form"; save.innerHTML = `<input name="name" value="My cover" maxlength="100" placeholder="${t("designName")}" /><button type="submit">${t("saveDesign")}</button><p class="profile-message"></p>`;
  save.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = String(new FormData(save).get("name"));
    const message = save.querySelector(".profile-message") as HTMLElement;
    try { await saveDesign(name, params); message.textContent = t("designSaved"); await renderProfile(data.user.id); }
    catch (error) { message.textContent = (error as Error).message; }
  });
  section.append(save);
  return section;
}

async function renderProfile(id: number): Promise<void> {
  profilePage.replaceChildren(Object.assign(document.createElement("p"), { className: "profile-loading", textContent: t("loadingProfile") }));
  try {
    const data = await fetchProfile(id);
    profilePage.replaceChildren();
    const top = document.createElement("div"); top.className = "profile-topbar";
    const back = document.createElement("button"); back.type = "button"; back.textContent = t("backConfigurator"); back.addEventListener("click", leaveProfile); top.append(back);
    if (data.is_owner) {
      const actions = document.createElement("div"); actions.className = "profile-top-actions";
      const signout = document.createElement("button"); signout.type = "button"; signout.textContent = t("signOut");
      signout.addEventListener("click", async () => { await signOut(); user = null; await renderAccount(authButton); navigateWorkshop(); });
      actions.append(signout); top.append(actions);
    }

    const header = document.createElement("header"); header.className = "profile-header";
    const avatar = avatarFor(data.user, data.is_owner, async (file, status) => {
      try {
        await uploadAvatar(file);
        status.textContent = t("uploadSaved");
        await renderAccount(authButton);
        await renderProfile(data.user.id);
      } catch (error) { status.textContent = (error as Error).message; }
    });
    header.append(avatar);
    const identity = document.createElement("div");
    const nickname = document.createElement("h1"); nickname.textContent = `@${data.user.nickname}`; identity.append(nickname);
    const fullName = [data.user.first_name, data.user.last_name].filter(Boolean).join(" ");
    if (fullName) identity.append(Object.assign(document.createElement("p"), { className: "profile-name", textContent: fullName }));
    if (data.user.city) identity.append(Object.assign(document.createElement("p"), { className: "profile-city", textContent: data.user.city }));
    if (data.is_owner && user) identity.append(Object.assign(document.createElement("p"), { className: "profile-email", textContent: user.email }));
    if (data.user.bio) identity.append(Object.assign(document.createElement("p"), { className: "profile-bio", textContent: data.user.bio }));
    const links = document.createElement("div"); links.className = "profile-links";
    for (const [label, href] of [[t("websiteLink"), data.user.website], [t("socialLink"), data.user.social_link]]) if (href) { const link = document.createElement("a"); link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = label; links.append(link); }
    if (links.childElementCount) identity.append(links); header.append(identity);

    const stats = document.createElement("div"); stats.className = "profile-stats";
    for (const [value, label] of [[String(data.stats.designs), "Designs"], [data.stats.average ? data.stats.average.toFixed(1) : "—", "Average rating"], [String(data.stats.ratings), "Ratings"]]) {
      const localizedLabel = label === "Designs" ? t("designs") : label === "Average rating" ? t("averageRating") : t("ratingsLabel");
      const item = document.createElement("div"); item.append(Object.assign(document.createElement("strong"), { textContent: value }), Object.assign(document.createElement("span"), { textContent: localizedLabel })); stats.append(item);
    }
    const designs = document.createElement("section"); designs.className = "profile-section"; designs.append(Object.assign(document.createElement("h2"), { textContent: t("allDesigns") }));
    const list = document.createElement("div"); list.className = "profile-designs";
    for (const design of data.designs) {
      const card = document.createElement("article"); card.className = "profile-design-card";
      const open = async () => { leaveProfile(); await openCommunityDesign(design.id); };
      card.addEventListener("click", () => void open());
      const name = document.createElement("button"); name.type = "button"; name.className = "profile-design-open"; name.textContent = design.name; name.addEventListener("click", (event) => { event.stopPropagation(); void open(); });
      const rating = document.createElement("span"); rating.textContent = design.rating.count ? `★ ${design.rating.average.toFixed(1)} · ${design.rating.count} ratings` : "No ratings yet";
      const date = document.createElement("time"); date.textContent = new Date(design.created_at * 1000).toLocaleDateString();
      rating.textContent = design.rating.count ? `★ ${design.rating.average.toFixed(1)} · ${design.rating.count} ${t("ratings")}` : t("noRatings");
      card.append(name, rating, date); list.append(card);
      if (data.is_owner) {
        const remove = document.createElement("button"); remove.type = "button"; remove.className = "profile-design-delete"; remove.textContent = t("delete");
        remove.addEventListener("click", async (event) => { event.stopPropagation(); await removeDesign(design.id); await renderProfile(data.user.id); }); card.append(remove);
      }
    }
    if (!data.designs.length) list.append(Object.assign(document.createElement("p"), { className: "community-empty", textContent: t("noPublished") }));
    designs.append(list);
    profilePage.append(top, header, stats, activityHeatmap(data.activity));
    if (data.is_owner) profilePage.append(ownerProfileTools(data));
    profilePage.append(designs);
  } catch (error) {
    profilePage.innerHTML = `<div class="profile-error"><h1>${t("profileUnavailable")}</h1><p>${escapeHtml((error as Error).message)}</p><button type="button">${t("backConfigurator")}</button></div>`;
    profilePage.querySelector("button")!.addEventListener("click", leaveProfile);
  }
}

/** Which preset, if any, the design still is. */
function activePreset(): string | null {
  for (const preset of schema.presets) {
    if (Object.entries(preset.values).every(([k, v]) => params[k] === v)) return preset.key;
  }
  return null;
}

function refreshPanel(): void {
  panel.setParams(params, activePreset());
  updateSpec();
}

function buildMasthead(): void {
  masthead.querySelectorAll(".masthead-title, .masthead-subtitle, .masthead-spec").forEach((node) => node.remove());
  specLine = null;
  const { title, subtitle, specLabel } = strings.masthead;
  if (has(title)) {
    const node = document.createElement("h1");
    node.className = "masthead-title";
    node.textContent = title;
    masthead.append(node);
  }
  if (has(subtitle)) {
    const node = document.createElement("p");
    node.className = "masthead-subtitle";
    node.textContent = subtitle;
    masthead.append(node);
  }
  const keys = Object.keys(strings.masthead.specKeys).filter((k) =>
    has(strings.masthead.specKeys[k]),
  );
  if (keys.length === 0) return;
  const line = document.createElement("p");
  line.className = "masthead-spec";
  if (has(specLabel)) {
    const tagged = document.createElement("span");
    tagged.className = "masthead-spec-label";
    tagged.textContent = specLabel;
    line.append(tagged);
  }
  specLine = document.createElement("span");
  line.append(specLine);
  masthead.append(line);
}

function workshopBottomUi(): void {
  workshopBottomBar = document.createElement("section");
  workshopBottomBar.className = "workshop-bottom-bar";
  workshopSaveArea = document.createElement("section");
  workshopSaveArea.className = "workshop-save-area";
  workshopRatingArea = document.createElement("section");
  workshopRatingArea.className = "workshop-rating-area";
  workshopBottomBar.append(workshopSaveArea, workshopRatingArea);
  document.body.insertBefore(workshopBottomBar, panelRoot);
  renderWorkshopSave();
  renderWorkshopRating(null);
}

async function refreshLocalizedUi(): Promise<void> {
  updateLanguageButton();
  headerActions.setAttribute("aria-label", t("accountCommunity"));
  const workshopButton = headerActions.querySelector(".workshop-button");
  if (workshopButton) { workshopButton.textContent = t("navWorkshop"); (workshopButton as HTMLElement).title = t("openConfigurator"); }
  const communityButton = headerActions.querySelector(".community-button");
  if (communityButton) communityButton.textContent = t("navCommunity");
  const profileButton = headerActions.querySelector(".profile-button");
  if (profileButton) { profileButton.textContent = t("navProfile"); (profileButton as HTMLElement).title = t("openProfile"); }
  if (!user && authButton) authButton.textContent = t("signInRegister");
  const communityTitle = communityDialog.querySelector(".group");
  if (communityTitle) communityTitle.textContent = t("community");
  const communityHeading = communityDialog.querySelector(".account-title");
  if (communityHeading) communityHeading.textContent = t("publicDesigns");
  const communitySearch = communityDialog.querySelector("[name=search]") as HTMLInputElement | null;
  if (communitySearch) communitySearch.placeholder = t("findDesign");
  const communitySearchButton = communityDialog.querySelector(".community-search button");
  if (communitySearchButton) communitySearchButton.textContent = t("search");
  buildMasthead();
  if (panel) {
    panel.refreshStrings();
    refreshPanel();
  }
  renderWorkshopSave();
  renderWorkshopRating(activeWorkshopDesign);
  if (!communityDialog.hidden) {
    const search = (communityDialog.querySelector("[name=search]") as HTMLInputElement).value;
    await renderCommunity(search);
  }
  if (!accountDialog.hidden) {
    await renderAccount(authButton);
    accountDialog.hidden = false;
  }
  const match = window.location.pathname.match(/^\/profile\/(\d+)\/?$/);
  if (match && !profilePage.hidden) await renderProfile(Number(match[1]));
}

function updateSpec(): void {
  if (!specLine) return;
  const { specKeys, specSeparator } = strings.masthead;
  const parts: string[] = [];
  for (const [key, letter] of Object.entries(specKeys)) {
    if (!has(letter)) continue;
    const range = schema.ranges[key];
    const value = Number(params[key]);
    const digits = range.step >= 1 ? 0 : range.step >= 0.1 ? 1 : 2;
    parts.push(`${letter}${value.toFixed(digits)}`);
  }
  const operation = strings.choices.operation.options[String(params.operation)];
  if (has(operation)) parts.push(operation.toUpperCase());
  // The picture is part of what the object is, so its digest goes on the
  // spec line: the same file and the same sliders rebuild the same cover.
  if (params.hole_shape === "image" && silhouette && has(strings.motif.specTag)) {
    parts.push(`${strings.motif.specTag} ${silhouette.short}`);
  }
  const material = schema.materials.find((m) => m.key === params.material);
  if (material) parts.push(material.label.toUpperCase());
  specLine.textContent = parts.join(specSeparator);
}

/** Read the held picture again after the threshold or smoothing moved. */
function reread(): void {
  clearTimeout(motifTimer);
  if (!silhouette) return;
  motifTimer = window.setTimeout(async () => {
    try {
      silhouette = await readMotif(params);
      panel.setSilhouette(silhouette, noteFor(silhouette));
      updateSpec();
    } catch {
      panel.setSilhouette(silhouette, strings.motif.unreadable);
    }
  }, DEBOUNCE_MS);
}

/** What the preview says about itself, if anything. */
function noteFor(shape: Silhouette): string {
  return shape.shapes === 0 ? strings.motif.empty : "";
}

async function takePicture(file: File): Promise<void> {
  panel.setSilhouette(silhouette, strings.motif.reading);
  try {
    silhouette = await uploadMotif(file);
  } catch {
    panel.setSilhouette(silhouette, strings.motif.unreadable);
    return;
  }
  // A new picture arrives at its own reading, so the two controls that would
  // otherwise still describe the last one go back to where they started.
  params.motif_id = silhouette.id;
  params.threshold_bias = schema.defaults.threshold_bias;
  params.motif_smoothing = schema.defaults.motif_smoothing;
  params.motif_invert = schema.defaults.motif_invert;
  panel.setSilhouette(silhouette, noteFor(silhouette));
  refreshPanel();
  request(false);
}

function request(draft: boolean): void {
  clearTimeout(timer);
  timer = window.setTimeout(() => void run(draft), draft ? DEBOUNCE_MS : 0);
}

async function run(draft: boolean): Promise<void> {
  inflight?.abort();
  const controller = new AbortController();
  inflight = controller;
  pending = true;
  panel.setBusy(true, draft ? strings.status.draft : strings.status.computing);
  try {
    const { glb, stats } = await fetchCover(params, draft, controller.signal);
    await viewer.setModel(glb);
    viewer.setFinish(stats.finish);
    panel.setStats(stats);
    panel.setCap("wall_thickness", stats.max_wall_thickness);
    panel.setCap("relief_depth", stats.max_relief_depth);
    applyAccent(stats.finish.colour_a);
    pending = false;
    panel.setBusy(false, "");
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    pending = false;
    panel.setBusy(false, strings.status.offline);
  }
}

async function start(): Promise<void> {
  schema = await fetchSchema();
  user = await currentUser();
  params = { ...schema.defaults };

  const first =
    schema.materials.find((m) => m.key === params.material) ?? schema.materials[0];
  viewer = new Viewer(stage, first.hex);
  applyAccent(first.hex);

  buildMasthead();
  workshopBottomUi();
  accountUi();
  communityUi();
  navigationUi();
  languageUi();
  profileUi();
  void renderAccount(authButton);
  panel = new Panel(panelRoot, schema, {
    onParam(key, value, live) {
      params[key] = value;
      refreshPanel();
      if (READING.has(key)) reread();
      request(live);
    },
    onChoice(key, value) {
      params[key] = value;
      refreshPanel();
      // Shading is drawn in the browser; only geometry needs the server.
      if (key === "finish") viewer.setFinish(finishOf());
      else request(false);
    },
    onToggle(key, value) {
      params[key] = value;
      refreshPanel();
      if (READING.has(key)) reread();
      request(false);
    },
    onMaterial(key, second) {
      params[second ? "colour_b" : "material"] = key;
      refreshPanel();
      if (!second) applyAccent(colourOf(key));
      viewer.setFinish(finishOf());
      // Density differs between polymers, so the weight has to come back.
      if (!second) request(false);
    },
    onPreset(preset: PresetSpec) {
      // A preset is a starting point: it moves the sliders and lets go.
      Object.assign(params, preset.values);
      refreshPanel();
      applyAccent(colourOf(String(params.material)));
      request(false);
    },
    onPicture(file: File) {
      void takePicture(file);
    },
    async onDownload(fmt) {
      panel.setDownloading(true);
      try {
        await downloadCover(params, fmt);
      } catch {
        panel.setBusy(pending, strings.status.offline);
      } finally {
        panel.setDownloading(false);
      }
    },
  });
  subscribe(() => { void refreshLocalizedUi(); });
  panel.setSilhouette(null, "");
  refreshPanel();
  void route();
  void run(false);
}

function colourOf(key: string): string {
  return schema.materials.find((m) => m.key === key)?.hex ?? "#17514c";
}

function finishOf() {
  return {
    mode: String(params.finish),
    colour_a: colourOf(String(params.material)),
    colour_b: colourOf(String(params.colour_b)),
    facet_scale: Number(params.facet_scale),
  };
}

void start();
