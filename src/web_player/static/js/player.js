"use strict";

/** Управляет воспроизведением и отображением единой серверной очереди. */
(() => {
  const element = (id) => document.getElementById(id);
  const audio = element("audio");
  const storageKey = "musical-palace-position";
  let state = null;
  let loadedId = null;
  let busy = false;
  let openingFile = false;
  let resumeAt = 0;
  let savedSecond = -1;
  const editor = new window.MetadataEditor({ onChange: render, onSave: applyMetadata });

  /** Обновляет сведения всех загруженных треков общей музыкальной директории. */
  function applyMetadata(data) {
    const tracks = [state.current, ...state.previous, ...state.upcoming];
    for (const track of tracks) {
      if (!track || track.directory !== data.directory) continue;
      if (track.id === data.track_id) track.name = data.filename + data.extension;
      track.description = data.description.trim();
      track.tags = Object.entries(data.tags).map(([key, value]) => ({
        name: data.definitions[key].name, display_name: data.definitions[key].display_name,
        type: data.definitions[key].type, value,
      }));
    }
  }

  /** Преобразует секунды в отображаемое время. */
  function time(seconds) {
    if (!Number.isFinite(seconds)) return "—:—";
    const value = Math.max(0, Math.floor(seconds));
    return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
  }

  /** Обновляет цветную часть полосы перемотки. */
  function updateSeekProgress() {
    const seek = element("seek");
    const duration = Number(seek.max);
    const position = Number(seek.value);
    const progress = duration > 0 ? Math.max(0, Math.min(100, position / duration * 100)) : 0;
    seek.style?.setProperty?.("--seek-progress", `${progress}%`);
  }

  /** Сохраняет позицию текущего трека в браузере. */
  function save() {
    if (!loadedId || audio.readyState === 0) return;
    try {
      localStorage.setItem(storageKey, JSON.stringify({ id: loadedId, time: audio.currentTime }));
    } catch { /* Воспроизведение доступно и при запрещённом хранилище. */ }
  }

  /** Восстанавливает время только для совпадающего текущего трека. */
  function savedPosition(id) {
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey));
      return stored?.id === id && Number.isFinite(stored.time) ? Math.max(0, stored.time) : 0;
    } catch { return 0; }
  }

  /** Запрашивает состояние серверной очереди. */
  async function request(action = "state") {
    const response = await fetch(`/api/${action}`, {
      method: action === "state" ? "GET" : "POST",
      cache: "no-store",
    });
    if (!response.ok) throw new Error("Сервер недоступен. Повторите действие.");
    return response.json();
  }

  const playlistButtons = new Map();
  let playlistOffset = 0;
  let playlistRevision = null;
  let playlistTask = null;
  let playlistGeneration = 0;
  let playlistInitialScrollPending = true;

  /** Прокручивает только панель плейлиста к текущей песне. */
  function scrollToCurrent() {
    const button = playlistButtons.get(state?.current?.id);
    if (!button || playlist.getAttribute("aria-hidden") === "true") return false;
    const panel = playlist.getBoundingClientRect();
    const row = button.getBoundingClientRect();
    playlist.scrollTo({
      top: playlist.scrollTop + row.top - panel.top - playlist.clientHeight / 2 + row.height / 2,
      behavior: "auto",
    });
    return true;
  }

  /** Обновляет подсветку без пересоздания уже загруженных строк. */
  function highlightPlaylist() {
    const tracks = [state?.current, ...(state?.previous ?? []), ...(state?.upcoming ?? [])];
    const names = new Map(tracks.filter(Boolean).map((track) => [track.id, track.name]));
    for (const [id, button] of playlistButtons) {
      if (names.has(id)) button.children[0].textContent = names.get(id);
      button.disabled = busy || editor.active;
      if (id === state?.current?.id) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    }
  }

  /** Загружает очередные сто строк и добавляет их в конец ленты. */
  function loadMoreTracks() {
    if (playlistTask) return playlistTask;
    if (!state || playlistOffset >= state.playlist_total) return Promise.resolve(false);
    const generation = playlistGeneration;
    element("playlist-more").hidden = true;
    element("playlist-status").textContent = "Загрузка…";
    playlistTask = (async () => {
      try {
        const response = await fetch(`/api/playlist?offset=${playlistOffset}`, { cache: "no-store" });
        if (!response.ok) throw new Error("Не удалось загрузить плейлист. Повторите попытку.");
        const page = await response.json();
        if (generation !== playlistGeneration) return false;
        if (page.revision !== state.playlist_revision) {
          throw new Error("Состав плейлиста изменился. Обновите страницу.");
        }
        for (const track of page.tracks) {
          const item = document.createElement("li");
          const button = document.createElement("button");
          button.className = "playlist-track";
          const filename = document.createElement("span");
          filename.className = "track-name";
          filename.textContent = track.name;
          const directory = document.createElement("small");
          directory.className = "track-directory";
          directory.textContent = track.directory;
          button.append(filename, directory);
          button.addEventListener("click", () => void change(`select/${encodeURIComponent(track.id)}`, true, false));
          item.append(button);
          element("playlist-tracks").append(item);
          playlistButtons.set(track.id, button);
        }
        playlistOffset = page.offset + page.tracks.length;
        element("playlist-status").textContent = "";
        highlightPlaylist();
        return page.tracks.length > 0;
      } catch (error) {
        if (generation === playlistGeneration) {
          element("playlist-status").textContent = error.message;
          element("playlist-more").hidden = false;
        }
        return false;
      } finally {
        if (generation === playlistGeneration) playlistTask = null;
      }
    })();
    return playlistTask;
  }

  /** Догружает ленту до текущего файла, сохраняя все предыдущие строки. */
  async function syncPlaylist(scrollCurrent = true) {
    if (playlistRevision !== state.playlist_revision) {
      playlistGeneration += 1;
      playlistTask = null;
      playlistRevision = state.playlist_revision;
      playlistOffset = 0;
      playlistButtons.clear();
      element("playlist-tracks").replaceChildren();
    }
    const target = Math.max(1, (state.current_index ?? 0) + 1);
    while (playlistOffset < target && playlistOffset < state.playlist_total) {
      if (!await loadMoreTracks()) break;
    }
    if (!state.playlist_total) element("playlist-status").textContent = "Нет треков";
    highlightPlaylist();
    if (scrollCurrent && scrollToCurrent()) playlistInitialScrollPending = false;
  }

  /** Обновляет сведения о треке, кнопки и окно очереди. */
  function render() {
    const track = state?.current;
    element("name").textContent = track?.name ?? "В библиотеке нет музыки";
    element("directory").textContent = track?.directory ?? "Добавьте записи и перезапустите сервер";
    const description = element("description");
    description.textContent = track?.description ?? "";
    element("description-section").hidden = editor.active || !track?.description;
    const tags = element("tags");
    tags.replaceChildren();
    const allTags = track?.tags ?? [];
    const lyrics = allTags.find((tag) => tag.name === "Lyrics");
    const rating = allTags.find((tag) => tag.name === "Rating");
    element("lyrics").textContent = lyrics?.value ?? "";
    element("lyrics-section").hidden = editor.active || !lyrics?.value;
    const stars = element("rating-stars");
    stars.replaceChildren();
    if (rating) {
      for (let number = 1; number <= 10; number += 1) {
        const star = document.createElement("span");
        const filled = number <= rating.value;
        star.className = filled ? "rating-star is-filled" : "rating-star";
        star.textContent = filled ? "★" : "☆";
        stars.append(star);
      }
    }
    element("rating-label").textContent = rating ? `${rating.value}/10` : "";
    element("track-rating").setAttribute("aria-label", rating ? `Оценка ${rating.value} из 10` : "Оценка не задана");
    element("track-rating").hidden = editor.active || !rating;
    const trackTags = allTags.filter((tag) => tag !== lyrics && tag !== rating);
    for (const tag of trackTags) {
      const term = document.createElement("dt");
      term.textContent = tag.display_name ?? tag.name;
      const value = document.createElement("dd");
      value.textContent = typeof tag.value === "boolean" ? (tag.value ? "Да" : "Нет")
        : Array.isArray(tag.value) ? tag.value.join(", ") : String(tag.value);
      tags.append(term, value);
    }
    element("tags-section").hidden = editor.active || !trackTags.length;
    const resources = element("resources");
    resources.replaceChildren();
    const trackResources = [
      ["Музыка", track?.music_count],
      ["LogicX", track?.logic_count],
      ["Табы", track?.tab_count],
    ].filter(([, count]) => count > 0);
    for (const [name, count] of trackResources) {
      const term = document.createElement("dt");
      term.textContent = name;
      const value = document.createElement("dd");
      value.textContent = String(count);
      resources.append(term, value);
    }
    element("resources-section").hidden = editor.active || !trackResources.length;
    element("count").textContent = state
      ? `Директории: ${state.total_directories} · Файлы: ${state.total}`
      : "";
    element("play").disabled = busy || !track;
    element("open-file").disabled = busy || !track || openingFile;
    element("edit-metadata").disabled = busy || !track;
    element("previous").disabled = busy || editor.active || !state?.has_previous;
    element("next").disabled = busy || editor.active || !state?.has_next;
    element("shuffle").disabled = busy || editor.active || !state?.has_next;
    element("previous-directory").hidden = Boolean(state?.shuffled);
    element("previous-directory").disabled = busy || editor.active || !state?.has_previous_directory;
    element("next-directory").hidden = Boolean(state?.shuffled);
    element("next-directory").disabled = busy || editor.active || !state?.has_next_directory;
    editor.render();
    highlightPlaylist();
    updateMediaSession();
  }

  /** Передаёт сведения о текущем треке и статус воспроизведения системному плееру. */
  function updateMediaSession() {
    if (!("mediaSession" in navigator)) return;
    const session = navigator.mediaSession;
    if (typeof MediaMetadata !== "undefined") {
      session.metadata = state?.current ? new MediaMetadata({
        title: state.current.name,
        artist: state.current.directory,
        album: "Музыкальные чертоги",
      }) : null;
    }
    session.playbackState = !state?.current ? "none" : audio.paused ? "paused" : "playing";
    updateMediaPosition();
  }

  /** Обновляет время в системном плеере только после загрузки длительности. */
  function updateMediaPosition() {
    if (!navigator.mediaSession?.setPositionState) return;
    try {
      if (!Number.isFinite(audio.duration) || audio.duration <= 0 || audio.readyState === 0) {
        navigator.mediaSession.setPositionState();
        return;
      }
      navigator.mediaSession.setPositionState({
        duration: audio.duration,
        playbackRate: audio.playbackRate,
        position: Math.max(0, Math.min(audio.currentTime, audio.duration)),
      });
    } catch { /* Браузер может не поддерживать обновление позиции. */ }
  }

  /** Подключает переключение файлов и воспроизведение с экрана блокировки. */
  function setupMediaSession() {
    if (!navigator.mediaSession?.setActionHandler) return;
    const handlers = {
      play: () => { if (!busy && state?.current) void play(); },
      pause: () => audio.pause(),
      previoustrack: () => { if (state?.has_previous) void change("previous", !audio.paused, false); },
      nexttrack: () => { if (state?.has_next) void change("next", !audio.paused, false); },
      seekbackward: null,
      seekforward: null,
      seekto: (event) => {
        if (!Number.isFinite(audio.duration) || !Number.isFinite(event.seekTime)) return;
        audio.currentTime = Math.max(0, Math.min(event.seekTime, audio.duration));
        save();
        updateMediaPosition();
      },
    };
    for (const [action, handler] of Object.entries(handlers)) {
      try {
        navigator.mediaSession.setActionHandler(action, handler);
      } catch { /* Неподдерживаемые действия не мешают работе плеера. */ }
    }
  }

  /** Загружает новый текущий трек, сохраняя позицию предыдущего. */
  function loadCurrent() {
    if (!state.current || loadedId === state.current.id) return;
    save();
    audio.pause();
    loadedId = state.current.id;
    resumeAt = savedPosition(loadedId);
    savedSecond = -1;
    element("seek").disabled = true;
    element("seek").value = 0;
    updateSeekProgress();
    element("elapsed").textContent = "0:00";
    element("duration").textContent = "—:—";
    audio.src = `/audio/${loadedId}`;
    audio.load();
  }

  /** Начинает воспроизведение с учётом ограничений браузера. */
  async function play() {
    try {
      if (audio.ended) audio.currentTime = 0;
      await audio.play();
    } catch (error) {
      if (error.name === "NotAllowedError") {
        element("status").textContent = "Нажмите Play для продолжения воспроизведения.";
      } else if (error.name !== "AbortError" && !audio.error) {
        element("status").textContent = "Не удалось начать воспроизведение. Нажмите Play ещё раз.";
      }
    }
  }

  /** Выполняет переход или перемешивание и применяет состояние сервера. */
  async function change(action, autoplay = !audio.paused, scrollPlaylist = true) {
    if (busy || editor.active) return;
    busy = true;
    render();
    try {
      state = await request(action);
      if (action !== "shuffle") loadCurrent();
      if (state.ended) {
        audio.pause();
        element("status").textContent = "Плейлист закончился.";
      } else if (action === "shuffle") {
        element("status").textContent = "Следующие треки перемешаны.";
      } else if (autoplay && state.current) {
        void play();
      }
      await syncPlaylist(scrollPlaylist);
    } catch (error) {
      element("status").textContent = error.message;
    } finally {
      busy = false;
      render();
    }
  }

  /** Показывает загруженный в браузере файл в Finder на компьютере сервера. */
  async function openFile() {
    if (busy || openingFile || !loadedId) return;
    openingFile = true;
    render();
    try {
      const response = await fetch(`/api/reveal/${encodeURIComponent(loadedId)}`, { method: "POST" });
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Не удалось открыть файл в Finder");
      }
      element("status").textContent = "Файл показан в Finder.";
    } catch (error) {
      element("status").textContent = error.message;
    } finally {
      openingFile = false;
      render();
    }
  }

  element("open-file").addEventListener("click", () => void openFile());
  element("edit-metadata").addEventListener("click", () => {
    if (!busy && state?.current) void editor.open(state.current);
  });
  element("play").addEventListener("click", () => {
    element("status").textContent = "";
    if (audio.paused) void play();
    else audio.pause();
  });
  element("previous").addEventListener("click", () => void change("previous"));
  element("next").addEventListener("click", () => void change("next"));
  element("previous-directory").addEventListener("click", () => void change("previous-directory"));
  element("next-directory").addEventListener("click", () => void change("next-directory"));
  element("shuffle").addEventListener("click", () => void change("shuffle"));
  const playlist = element("playlist");
  const mobileLayout = window.matchMedia("(max-width: 767px)");

  window.addEventListener("pageshow", () => {
    const activeElement = document.activeElement;
    if (activeElement && playlist.contains(activeElement)) activeElement.blur();
  });

  /** Переключает постоянную боковую панель и закрытое мобильное окно. */
  function syncPlaylistLayout() {
    playlist.classList.remove("is-open");
    playlist.setAttribute("aria-hidden", String(mobileLayout.matches));
    element("toggle-playlist").setAttribute("aria-expanded", "false");
    element("toggle-playlist").setAttribute("aria-pressed", "false");
  }

  element("toggle-playlist").addEventListener("click", () => {
    if (!mobileLayout.matches) return;
    const isOpen = playlist.classList.toggle("is-open");
    playlist.setAttribute("aria-hidden", String(!isOpen));
    element("toggle-playlist").setAttribute("aria-expanded", String(isOpen));
    element("toggle-playlist").setAttribute("aria-pressed", String(isOpen));
    if (isOpen && playlistInitialScrollPending && scrollToCurrent()) playlistInitialScrollPending = false;
  });
  playlist.addEventListener("scroll", () => {
    if ((!mobileLayout.matches || playlist.classList.contains("is-open"))
      && playlist.scrollHeight - playlist.scrollTop - playlist.clientHeight < 160) {
      void loadMoreTracks();
    }
  });
  element("playlist-more").addEventListener("click", () => void loadMoreTracks());
  mobileLayout.addEventListener("change", syncPlaylistLayout);
  syncPlaylistLayout();
  element("seek").addEventListener("input", (event) => {
    if (Number.isFinite(audio.duration)) audio.currentTime = Number(event.target.value);
    updateSeekProgress();
    save();
  });
  audio.addEventListener("loadedmetadata", () => {
    if (!Number.isFinite(audio.duration)) return;
    element("duration").textContent = time(audio.duration);
    element("seek").max = audio.duration;
    element("seek").disabled = false;
    if (resumeAt > 0 && resumeAt < audio.duration) audio.currentTime = resumeAt;
    updateSeekProgress();
    resumeAt = 0;
    updateMediaPosition();
  });
  audio.addEventListener("timeupdate", () => {
    element("elapsed").textContent = time(audio.currentTime);
    element("seek").value = audio.currentTime;
    updateSeekProgress();
    if (Math.floor(audio.currentTime) !== savedSecond) {
      save();
      savedSecond = Math.floor(audio.currentTime);
      updateMediaPosition();
    }
  });
  audio.addEventListener("play", () => {
    element("play-icon").hidden = true;
    element("pause-icon").hidden = false;
    element("play").setAttribute("aria-label", "Пауза");
    updateMediaSession();
  });
  audio.addEventListener("pause", () => {
    element("play-icon").hidden = false;
    element("pause-icon").hidden = true;
    element("play").setAttribute("aria-label", "Воспроизвести");
    save();
    updateMediaSession();
  });
  audio.addEventListener("ended", () => {
    if (editor.active) {
      element("status").textContent = "Трек закончился. Завершите редактирование и нажмите Play или выберите другой трек.";
      return;
    }
    void change("next", true, false);
  });
  audio.addEventListener("error", () => {
    element("status").textContent = `Не удалось воспроизвести «${state?.current?.name}».`;
    if (state?.has_next) void change("next", true, false);
    else {
      audio.pause();
      element("status").textContent += " Доступных следующих треков нет.";
    }
  });
  window.addEventListener("pagehide", save);
  document.addEventListener("visibilitychange", save);

  /** Загружает состояние сервера без автоматического запуска звука. */
  async function init() {
    try {
      state = await request();
      render();
      loadCurrent();
      await syncPlaylist();
    } catch (error) {
      element("name").textContent = "Не удалось загрузить библиотеку";
      element("directory").textContent = "Обновите страницу для повторной попытки";
      element("status").textContent = error.message;
    }
  }
  setupMediaSession();
  void init();
})();
