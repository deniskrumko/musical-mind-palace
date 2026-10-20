/** Проверяет взаимодействие интерфейса с системным плеером и серверной очередью. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

/** Представляет минимальные элементы страницы и события аудио для проверки обработчиков. */
class Element {
  /** Создаёт состояние элемента и аудиоплеера. */
  constructor(tagName) {
    this.tagName = tagName;
    this.scrollTop = 0;
    this.scrollHeight = 2000;
    this.clientHeight = 600;
    this.listeners = {};
    this.children = [];
    this.paused = true;
    this.readyState = 0;
    this.currentTime = 0;
    this.duration = NaN;
    this.playbackRate = 1;
    this.value = "";
    this.classes = new Set();
    this.classList = {
      add: name => this.classes.add(name),
      remove: name => this.classes.delete(name),
      contains: name => this.classes.has(name),
      toggle: (name, force) => {
        if (force === false || (force === undefined && this.classes.has(name))) {
          this.classes.delete(name);
          return false;
        }
        this.classes.add(name);
        return true;
      },
    };
  }
  /** Регистрирует обработчик события. */
  addEventListener(type, handler) { (this.listeners[type] ??= []).push(handler); }
  /** Вызывает зарегистрированные обработчики. */
  emit(type) {
    const event = { target: this, preventDefault() { this.defaultPrevented = true; } };
    for (const handler of this.listeners[type] ?? []) handler(event);
    return event;
  }
  /** Очищает дочерние элементы. */
  replaceChildren() { this.children = []; }
  /** Добавляет дочерние элементы. */
  append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } }
  /** Удаляет строку из родительского списка. */
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); }
  /** Отмечает перенос фокуса в поле редактора. */
  focus() { this.focused = true; }
  /** Запоминает атрибут элемента. */
  setAttribute(name, value) { this[name] = value; }
  /** Возвращает атрибут элемента. */
  getAttribute(name) { return this[name] ?? null; }
  /** Удаляет атрибут выделения. */
  removeAttribute(name) { delete this[name]; }
  /** Возвращает размеры строки для проверки прокрутки панели. */
  getBoundingClientRect() { return {top: 100, height: 44}; }
  /** Запоминает программную прокрутку панели. */
  scrollTo(options) { this.scrollTop = Math.max(0, options.top); this.scrollCalls = (this.scrollCalls ?? 0) + 1; }
  /** Открывает обычную боковую панель. */
  show() { this.open = true; this.modal = false; }
  /** Открывает модальное окно. */
  showModal() { this.open = true; this.modal = true; }
  /** Закрывает окно и отправляет событие. */
  close() { if (this.open) { this.open = false; this.modal = false; this.emit("close"); } }
  /** Сбрасывает метаданные при смене аудио. */
  load() { this.currentTime = 0; this.readyState = 0; this.duration = NaN; }
  /** Приостанавливает воспроизведение с отправкой события. */
  pause() { if (!this.paused) { this.paused = true; this.emit("pause"); } }
  /** Запускает воспроизведение с отправкой события. */
  async play() { this.paused = false; this.emit("play"); }
}

/** Ожидает завершения асинхронных обработчиков интерфейса. */
function settle() { return new Promise(resolve => setImmediate(resolve)); }

/** Создаёт изолированную страницу с подготовленными ответами сервера. */
async function page(withMedia = true, unsupportedActions = false, trackCount = 5, currentIndex = 0) {
  const tracks = [
    { id: "a1", name: "1.mp3", directory: "А" },
    { id: "a2", name: "<img src=x>.mp3", directory: "А" },
    { id: "b1", name: "1.mp3", directory: "Б" },
    { id: "b2", name: "2.mp3", directory: "Б" },
    { id: "c1", name: "1.mp3", directory: "В" },
  ];
  while (tracks.length < trackCount) {
    tracks.push({id: `t${tracks.length}`, name: `${tracks.length}.mp3`, directory: "Д"});
  }
  let order = [...tracks];
  const [a1, a2, b1, b2, c1] = tracks;
  const initial = { current: tracks[currentIndex], previous: tracks.slice(0, currentIndex), upcoming: tracks.slice(currentIndex + 1), total: trackCount, total_directories: 3,
    current_index: currentIndex, playlist_total: trackCount, playlist_revision: 0,
    has_previous: false, has_next: true, has_previous_directory: currentIndex > 0, has_next_directory: true, shuffled: false, ended: false };
  const replies = {
    state: initial,
    next: { ...initial, current_index: 1, current: a2, previous: [a1], upcoming: [b1, b2, c1], has_previous: true },
    previous: initial,
    a2: { ...initial, current_index: 1, current: a2, previous: [a1], upcoming: [b1, b2, c1], has_previous: true },
    "next-directory": { ...initial, current_index: 2, current: b1, previous: [a1], upcoming: [b2, c1], has_previous: true },
    "previous-directory": initial,
    shuffle: { ...initial, playlist_revision: 1, current_index: 0, current: a1, previous: [], upcoming: [a2, b2, b1],
      has_previous: true, shuffled: true, has_next_directory: false },
  };
  const elements = new Map();
  /** Находит созданные редактором поля среди потомков страницы. */
  const find = (node, id) => node.id === id ? node : node.children.map(child => find(child, id)).find(Boolean);
  const get = id => {
    for (const node of elements.values()) {
      const found = find(node, id);
      if (found) return found;
    }
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const handlers = {};
  const windowHandlers = {};
  const layout = { matches: false, addEventListener(type, handler) { this.onChange = handler; } };
  const calls = [];
  const media = {
    setActionHandler(action, handler) {
      if (unsupportedActions && action === "seekto") throw new Error("Не поддерживается");
      handlers[action] = handler;
    },
    setPositionState(value) {
      if (unsupportedActions) throw new Error("Не поддерживается");
      this.position = value;
    },
  };
  const metadataServer = { error: null, writes: [], data: {
    directory: "А", revision: "initial", description: "# Песня\n\nОписание\n\n",
    track_id: "a1", filename: "1", extension: ".mp3", file_revision: "audio-initial",
    tags: { other_names: ["Название"], rating: 3, mood: ["sad"] },
    definitions: {
      original_folder: {name: "Original folder", display_name: "Директория", type: "string"},
      other_names: {name: "Other names", display_name: "Другие названия", type: "list"},
      genre: {name: "Genre", display_name: "Жанр", type: "single_choice", choices: ["piano", "heavy"]},
      lyrics: {name: "Lyrics", display_name: "Текст песни", type: "text"},
      mood: {name: "Mood", display_name: "Настроение", type: "multi_choice", choices: ["sad", "kind"]},
      rating: {name: "Rating", display_name: "Оценка", type: "star_rating"},
    },
  }};
  const context = vm.createContext({
    navigator: withMedia ? { mediaSession: media } : {},
    MediaMetadata: class { constructor(data) { Object.assign(this, data); } },
    document: { getElementById: get, createElement: tag => new Element(tag), addEventListener() {} },
    window: { addEventListener(type, handler) { (windowHandlers[type] ??= []).push(handler); }, matchMedia: () => layout },
    localStorage: { getItem: () => null, setItem() {} },
    fetch: async (url, options) => {
      calls.push([url, options.method ?? "GET"]);
      if (url.startsWith("/api/metadata/")) {
        if (options.method === "PUT") {
          const update = JSON.parse(options.body);
          metadataServer.writes.push(update);
          if (metadataServer.error) return {ok: false, json: async () => ({detail: metadataServer.error})};
          metadataServer.data = { ...metadataServer.data, ...update, revision: "saved", file_revision: "audio-saved" };
          a1.name = update.filename + metadataServer.data.extension;
        }
        return {ok: true, json: async () => structuredClone(metadataServer.data)};
      }
      if (url.startsWith("/api/playlist?")) {
        const offset = Number(url.split("=")[1]);
        return {ok: true, json: async () => structuredClone({
          tracks: order.slice(offset, offset + 100), offset, total: order.length,
          revision: order[3]?.id === "c1" ? 1 : 0,
        })};
      }
      if (url === "/api/shuffle") order = [a1, a2, b1, c1, b2];
      return { ok: true, json: async () => structuredClone(replies[url.split("/").at(-1)]) };
    },
  });
  for (const file of ["metadata-editor.js", "player.js"]) {
    const source = fs.readFileSync(path.join(__dirname, "../../src/web_player/static/js", file), "utf8");
    vm.runInContext(source, context);
  }
  await settle();
  return { get, handlers, calls, media, layout, windowHandlers, metadataServer };
}

/** Проверяет черновик, поля редактора и остановку переходов до завершения правок. */
async function testMetadataEditor() {
  const { get, handlers, calls, media, metadataServer, windowHandlers } = await page();
  const audio = get("audio");
  audio.readyState = 1;
  audio.duration = 120;
  audio.currentTime = 40;
  await audio.play();
  get("edit-metadata").emit("click");
  const beforeLoadingEnds = calls.length;
  audio.emit("ended");
  assert.equal(calls.length, beforeLoadingEnds);
  await settle();
  assert.equal(get("metadata-form").hidden, false);
  assert.equal(audio.paused, false);
  assert.equal(audio.currentTime, 40);
  assert.equal(get("description-section").hidden, true);
  assert.equal(get("next").disabled, true);
  assert.equal(get("playlist-tracks").children[1].children[0].disabled, true);
  assert.equal(get("metadata-description").value, metadataServer.data.description);
  const fields = get("metadata-fields");
  assert.equal(fields.children.length, 8);
  assert.equal(get("metadata-filename").value, "1");
  get("metadata-filename").value = "Новое имя";
  assert.equal(get("metadata-rating").children.filter(child => child.tagName === "button").length, 10);
  assert.equal(get("metadata-rating").children[2]["aria-pressed"], "true");
  get("metadata-rating").children[7].emit("click");
  assert.equal(get("metadata-rating").children[7].classList.contains("is-filled"), true);
  assert.equal(get("metadata-rating").children[8].classList.contains("is-filled"), false);
  const list = get("metadata-other_names");
  list.children[1].emit("click");
  assert.equal(list.children[0].children.length, 2);
  list.children[0].children[1].children[0].value = "Второе название";
  list.children[0].children[0].children[1].emit("click");
  assert.equal(list.children[0].children.length, 1);
  get("metadata-genre").value = "piano";
  get("metadata-mood").children[1].children[0].checked = true;
  get("metadata-lyrics").value = "Куплет\nПрипев";
  get("metadata-description").value = "# Новое описание";
  const unload = { preventDefault() { this.prevented = true; } };
  windowHandlers.beforeunload[0](unload);
  assert.equal(unload.prevented, true);
  const blockedAt = calls.length;
  get("next").emit("click");
  get("shuffle").emit("click");
  get("playlist-tracks").children[1].children[0].emit("click");
  handlers.nexttrack();
  handlers.previoustrack();
  audio.emit("ended");
  await settle();
  assert.equal(calls.length, blockedAt);
  get("open-file").emit("click");
  await settle();
  assert.equal(get("metadata-description").value, "# Новое описание");
  get("metadata-form").emit("submit");
  await settle();
  assert.equal(metadataServer.writes.length, 1);
  assert.deepEqual(metadataServer.writes[0], {
    revision: "initial", description: "# Новое описание",
    file_revision: "audio-initial", filename: "Новое имя",
    tags: {other_names: ["Второе название"], genre: "piano", lyrics: "Куплет\nПрипев", mood: ["sad", "kind"], rating: 8},
  });
  assert.equal(get("metadata-form").hidden, true);
  assert.equal(get("description").textContent, "# Новое описание");
  assert.equal(get("lyrics").textContent, "Куплет\nПрипев");
  assert.equal(get("lyrics-section").hidden, false);
  assert.equal(get("track-rating").hidden, false);
  assert.equal(get("rating-stars").children.length, 10);
  assert.equal(get("rating-stars").children.filter(star => star.className.includes("is-filled")).length, 8);
  assert.equal(get("rating-label").textContent, "8/10");
  assert.equal(get("tags").children.some(tag => ["Lyrics", "Rating"].includes(tag.textContent)), false);
  assert.equal(get("next").disabled, false);
  assert.equal(audio.paused, false);
  assert.equal(audio.currentTime, 40);
  assert.equal(audio.src, "/audio/a1");
  assert.equal(get("name").textContent, "Новое имя.mp3");
  assert.equal(get("playlist-tracks").children[0].children[0].children[0].textContent, "Новое имя.mp3");
  assert.equal(media.metadata.title, "Новое имя.mp3");
  const clean = { preventDefault() { this.prevented = true; } };
  windowHandlers.beforeunload[0](clean);
  assert.equal(clean.prevented, undefined);

  get("edit-metadata").emit("click");
  await settle();
  get("metadata-description").value = "Несохранённые правки";
  get("metadata-filename").value = "Несохранённое имя";
  assert.equal(get("lyrics-section").hidden, true);
  assert.equal(get("track-rating").hidden, true);
  metadataServer.error = "INDEX.md изменился на диске. Изменения не сохранены.";
  get("metadata-form").emit("submit");
  await settle();
  assert.equal(get("status").textContent, metadataServer.error);
  assert.equal(get("metadata-form").hidden, false);
  assert.equal(get("metadata-description").value, "Несохранённые правки");
  assert.equal(get("metadata-filename").value, "Несохранённое имя");
  assert.equal(get("save-metadata").disabled, false);
  audio.paused = true;
  audio.ended = true;
  audio.currentTime = 120;
  audio.emit("ended");
  get("cancel-metadata").emit("click");
  await settle();
  assert.equal(audio.paused, true);
  assert.equal(get("description").textContent, "# Новое описание");
  assert.equal(get("name").textContent, "Новое имя.mp3");
  const beforePlay = calls.length;
  handlers.play();
  await settle();
  assert.equal(calls.length, beforePlay);
  assert.equal(audio.currentTime, 0);
  assert.equal(audio.paused, false);

  metadataServer.error = null;
  get("edit-metadata").emit("click");
  await settle();
  for (const field of get("metadata-fields").children) field.children[0].children[1]?.emit("click");
  audio.paused = true;
  audio.ended = true;
  audio.currentTime = 120;
  audio.emit("ended");
  get("metadata-form").emit("submit");
  await settle();
  assert.deepEqual(metadataServer.writes.at(-1).tags, {});
  assert.equal(metadataServer.writes.at(-1).description, "");
  assert.equal(audio.paused, true);
  assert.equal(get("metadata-form").hidden, true);
  assert.equal(get("description-section").hidden, true);
  assert.equal(get("tags-section").hidden, true);
  assert.equal(get("lyrics-section").hidden, true);
  assert.equal(get("track-rating").hidden, true);
  assert.equal(get("lyrics").textContent, "");
  assert.equal(get("rating-label").textContent, "");
}

/** Проверяет команды системного плеера, группировку и сохранение паузы. */
async function main() {
  await testMetadataEditor();
  const { get, handlers, calls, media, layout } = await page();
  assert.equal(get("playlist")["aria-hidden"], "false");
  layout.matches = true;
  layout.onChange();
  assert.equal(get("playlist")["aria-hidden"], "true");
  get("toggle-playlist").emit("click");
  assert.equal(get("playlist").classList.contains("is-open"), true);
  assert.equal(get("playlist")["aria-hidden"], "false");
  assert.equal(get("toggle-playlist")["aria-expanded"], "true");
  assert.equal(get("toggle-playlist")["aria-pressed"], "true");
  get("toggle-playlist").emit("click");
  assert.equal(get("playlist").classList.contains("is-open"), false);
  assert.equal(get("playlist")["aria-hidden"], "true");
  assert.equal(get("toggle-playlist")["aria-expanded"], "false");
  assert.equal(get("toggle-playlist")["aria-pressed"], "false");
  get("toggle-playlist").emit("click");
  layout.matches = false;
  layout.onChange();
  assert.equal(get("playlist")["aria-hidden"], "false");
  assert.equal(get("playlist").classList.contains("is-open"), false);
  const audio = get("audio");
  assert.equal(media.metadata.title, "1.mp3");
  assert.equal(get("count").textContent, "Директории: 3 · Файлы: 5");
  assert.equal(media.metadata.artist, "А");
  assert.equal(media.playbackState, "paused");
  assert.equal(get("open-file").disabled, false);
  get("open-file").emit("click");
  await settle();
  assert.deepEqual(calls.at(-1), ["/api/reveal/a1", "POST"]);
  assert.equal(audio.src, "/audio/a1");
  assert.equal(audio.paused, true);
  assert.equal(get("status").textContent, "Файл показан в Finder.");
  assert.equal(handlers.seekbackward, null);
  assert.equal(handlers.seekforward, null);
  assert.equal(get("next-directory").hidden, false);
  assert.equal(get("next-directory").disabled, false);
  const list = get("playlist-tracks");
  assert.equal(list.children.length, 5);
  const firstRow = list.children[0];
  const trackButton = list.children[1].children[0];
  assert.equal(trackButton.tagName, "button");
  assert.equal(trackButton.children[0].textContent, "<img src=x>.mp3");
  assert.equal(trackButton.children[1].tagName, "small");
  assert.equal(trackButton.children[1].textContent, "А");
  trackButton.emit("click");
  await settle();
  assert.deepEqual(calls.filter(call => call[1] === "POST").at(-1), ["/api/select/a2", "POST"]);
  assert.equal(audio.src, "/audio/a2");
  assert.equal(audio.paused, false);
  assert.equal(list.children[0], firstRow);
  get("open-file").emit("click");
  await settle();
  assert.deepEqual(calls.at(-1), ["/api/reveal/a2", "POST"]);
  assert.equal(audio.paused, false);
  assert.equal(list.children[1].children[0]["aria-current"], "true");
  assert.equal(firstRow.children[0]["aria-current"], undefined);
  assert.ok(get("playlist").scrollCalls > 0);
  handlers.previoustrack();
  await settle();
  handlers.pause();
  audio.readyState = 1;
  audio.duration = 90;
  audio.emit("loadedmetadata");
  handlers.seekto({ seekTime: 20 });
  assert.equal(audio.currentTime, 20);
  assert.equal(media.position.position, 20);
  handlers.play();
  await settle();
  assert.equal(media.playbackState, "playing");
  handlers.nexttrack();
  await settle();
  assert.deepEqual(calls.at(-1), ["/api/next", "POST"]);
  assert.equal(audio.src, "/audio/a2");
  assert.equal(audio.paused, false);
  assert.equal(media.metadata.title, "<img src=x>.mp3");
  handlers.previoustrack();
  await settle();
  assert.deepEqual(calls.at(-1), ["/api/previous", "POST"]);
  assert.equal(audio.src, "/audio/a1");
  handlers.pause();
  get("next-directory").emit("click");
  await settle();
  assert.deepEqual(calls.at(-1), ["/api/next-directory", "POST"]);
  assert.equal(audio.src, "/audio/b1");
  assert.equal(audio.paused, true);
  get("previous-directory").emit("click");
  await settle();
  assert.deepEqual(calls.at(-1), ["/api/previous-directory", "POST"]);
  assert.equal(audio.src, "/audio/a1");
  handlers.play();
  await settle();
  get("shuffle").emit("click");
  await settle();
  assert.equal(get("next-directory").hidden, true);
  assert.equal(audio.src, "/audio/a1");
  assert.equal(audio.paused, false);
  assert.equal(get("playlist-tracks").children.length, 5);
  assert.equal(typeof handlers.nexttrack, "function");
  const fallback = await page(false);
  fallback.get("next-directory").emit("click");
  await settle();
  assert.equal(fallback.get("audio").src, "/audio/b1");
  const partial = await page(true, true);
  partial.handlers.play();
  await settle();
  assert.equal(partial.media.playbackState, "playing");
  const paged = await page(true, false, 205);
  assert.equal(paged.get("playlist-tracks").children.length, 100);
  paged.get("playlist").scrollTop = 2000;
  paged.get("playlist").emit("scroll");
  await settle();
  assert.equal(paged.get("playlist-tracks").children.length, 200);
  paged.get("playlist").emit("scroll");
  await settle();
  assert.equal(paged.get("playlist-tracks").children.length, 205);
  const restored = await page(true, false, 205, 204);
  await settle();
  assert.equal(restored.get("playlist-tracks").children.length, 205);
  assert.equal(restored.get("playlist-tracks").children[204].children[0]["aria-current"], "true");
  assert.ok(restored.get("playlist").scrollCalls > 0);
  const requestCount = paged.calls.length;
  paged.get("playlist").emit("scroll");
  await settle();
  assert.equal(paged.calls.length, requestCount);
  layout.matches = true;
  layout.onChange();
  get("toggle-playlist").emit("click");
  assert.ok(get("playlist").scrollCalls > 1);
  console.log("Проверены системные кнопки, единая лента, подсветка и подгрузка по 100 файлов.");
}

main().catch(error => { console.error(error); process.exitCode = 1; });
