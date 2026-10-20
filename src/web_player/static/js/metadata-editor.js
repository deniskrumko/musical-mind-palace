/** Редактирует имя аудиофайла, описание и теги музыкальной директории. */
(() => {
  const element = (id) => document.getElementById(id);

  /** Управляет формой, черновиком и сохранением индекса на сервере. */
  class MetadataEditor {
    /** Подключает действия формы и предупреждение о несохранённых изменениях. */
    constructor({ onChange, onSave }) {
      this.onChange = onChange;
      this.onSave = onSave;
      this.track = null;
      this.loading = false;
      this.saving = false;
      this.fields = [];
      this.initial = "";
      this.generation = 0;
      element("metadata-form").addEventListener("submit", (event) => {
        event.preventDefault();
        void this.save();
      });
      element("cancel-metadata").addEventListener("click", () => this.close());
      window.addEventListener("beforeunload", (event) => {
        if (!this.dirty && !this.saving) return;
        event.preventDefault();
        event.returnValue = "";
      });
    }

    /** Показывает, что редактор удерживает текущий трек. */
    get active() { return this.track !== null; }

    /** Определяет наличие изменений значений относительно открытого индекса. */
    get dirty() {
      return this.active && !this.loading && JSON.stringify(this.values()) !== this.initial;
    }

    /** Обновляет доступность кнопок и полей без пересоздания черновика. */
    render() {
      element("edit-metadata").hidden = this.active;
      element("metadata-actions").hidden = !this.active;
      element("metadata-form").hidden = !this.active || this.loading;
      element("metadata-fields").disabled = this.saving;
      element("save-metadata").disabled = this.loading || this.saving;
      element("cancel-metadata").disabled = this.saving;
    }

    /** Загружает исходные значения с диска и строит форму по конфигурации. */
    async open(track) {
      if (this.active) return;
      this.track = track;
      const generation = ++this.generation;
      this.loading = true;
      element("status").textContent = "Загрузка данных для редактирования…";
      this.onChange();
      try {
        const data = await this.request("GET");
        if (this.generation !== generation) return;
        this.data = data;
        this.build();
        this.loading = false;
        this.initial = JSON.stringify(this.values());
        element("status").textContent = "";
      } catch (error) {
        if (this.generation !== generation) return;
        this.track = null;
        this.loading = false;
        element("status").textContent = error.message;
      }
      this.onChange();
    }

    /** Отправляет данные редактора и возвращает понятную ошибку сервера. */
    async request(method, body) {
      const response = await fetch(`/api/metadata/${encodeURIComponent(this.track.id)}`, {
        method,
        cache: "no-store",
        ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
      });
      if (!response.ok) {
        const error = await response.json();
        throw new Error(typeof error.detail === "string" ? error.detail : "Не удалось обработать данные индекса.");
      }
      return response.json();
    }

    /** Собирает значения полей, исключая очищенные теги. */
    values() {
      const tags = {};
      for (const field of this.fields) {
        const value = field.get();
        if (value !== null && value !== "" && (!Array.isArray(value) || value.length)) {
          tags[field.key] = value;
        }
      }
      return { filename: this.filename.value, description: this.description.value, tags };
    }

    /** Сохраняет индекс, оставляя черновик открытым при любой ошибке. */
    async save() {
      if (!this.active || this.loading || this.saving) return;
      this.saving = true;
      element("status").textContent = "Сохранение…";
      this.onChange();
      try {
        const data = await this.request("PUT", {
          revision: this.data.revision,
          file_revision: this.data.file_revision,
          ...this.values(),
        });
        this.onSave(data);
        this.saving = false;
        this.close();
        element("status").textContent = "Имя файла, описание и теги сохранены.";
      } catch (error) {
        this.saving = false;
        element("status").textContent = error.message;
        this.onChange();
      }
    }

    /** Закрывает форму, отбрасывая несохранённые изменения. */
    close() {
      if (this.saving) return;
      this.track = null;
      this.generation += 1;
      this.loading = false;
      this.fields = [];
      element("metadata-fields").replaceChildren();
      element("status").textContent = "";
      this.onChange();
      element("edit-metadata").focus();
    }

    /** Создаёт кнопку действия, не отправляющую форму. */
    button(text, label, action) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = text;
      button.setAttribute("aria-label", label);
      button.title = label;
      button.addEventListener("click", action);
      return button;
    }

    /** Добавляет подпись, кнопку очистки и элемент ввода в форму. */
    appendField(key, name, control, clearable = true) {
      const section = document.createElement("section");
      section.className = "editor-field";
      const heading = document.createElement("div");
      heading.className = "editor-field-heading";
      const label = document.createElement("label");
      label.textContent = name;
      label.id = `metadata-label-${key}`;
      control.element.id = `metadata-${key}`;
      label.htmlFor = control.element.id;
      control.element.setAttribute("aria-labelledby", label.id);
      heading.append(label);
      if (clearable) {
        const clear = this.button("", `Очистить поле «${name}»`, control.clear);
        clear.className = "clear-field";
        const icon = document.createElement("span");
        icon.className = "control-icon icon-trash";
        icon.setAttribute("aria-hidden", "true");
        clear.append(icon);
        heading.append(clear);
      }
      section.append(heading);
      if (control.extension) {
        const row = document.createElement("div");
        row.className = "editor-filename";
        const extension = document.createElement("span");
        extension.className = "filename-extension muted";
        extension.textContent = control.extension;
        row.append(control.element, extension);
        section.append(row);
      } else section.append(control.element);
      element("metadata-fields").append(section);
    }

    /** Создаёт поле строки или текста. */
    simpleControl(definition, value) {
      const type = definition.type;
      const input = document.createElement(type === "text" ? "textarea" : "input");
      if (type === "text") input.rows = 3;
      else input.type = "text";
      input.value = value ?? "";
      return {
        element: input,
        get: () => input.value.trim() ? input.value : null,
        clear: () => { input.value = ""; input.focus(); },
      };
    }

    /** Создаёт три кнопки для логического тега, включая неопределённое значение. */
    booleanControl(definition, value) {
      const container = document.createElement("div");
      container.className = "editor-choices";
      container.setAttribute("role", "group");
      let selected = typeof value === "boolean" ? value : null;
      const options = [[true, "Да"], [false, "Нет"], [null, "Не указано"]];
      const buttons = [];
      /** Обновляет выбранное состояние кнопок логического поля. */
      const update = () => {
        buttons.forEach(({ button, option }) => {
          button.setAttribute("aria-pressed", String(selected === option));
        });
      };
      for (const [option, text] of options) {
        const button = this.button(text, `${definition.display_name}: ${text}`, () => {
          selected = option;
          update();
        });
        buttons.push({ button, option });
        container.append(button);
      }
      update();
      return {
        element: container,
        get: () => selected,
        clear: () => { selected = null; update(); },
      };
    }

    /** Создаёт список отдельных строк с добавлением и удалением элементов. */
    listControl(definition, values) {
      const container = document.createElement("div");
      container.setAttribute("role", "group");
      const list = document.createElement("div");
      list.className = "editor-list";
      let rows = [];
      /** Добавляет строку списка и кнопку её удаления. */
      const addRow = (value = "") => {
        const row = document.createElement("div");
        row.className = "editor-list-row";
        const input = document.createElement("input");
        input.type = "text";
        input.value = value;
        input.setAttribute("aria-label", `${definition.display_name}: значение`);
        const remove = this.button("−", "Удалить строку", () => {
          rows = rows.filter((item) => item !== input);
          row.remove();
          if (!rows.length) addRow();
          rows.at(-1).focus();
        });
        row.append(input, remove);
        rows.push(input);
        list.append(row);
        return input;
      };
      const add = this.button("+", `Добавить строку: ${definition.display_name}`, () => addRow().focus());
      add.className = "add-list-row";
      for (const value of values?.length ? values : [""]) addRow(value);
      container.append(list, add);
      return {
        element: container,
        get: () => rows.map((input) => input.value.trim()).filter(Boolean),
        clear: () => { rows = []; list.replaceChildren(); addRow().focus(); },
      };
    }

    /** Создаёт группу кнопок с одиночным или множественным выбором. */
    choiceControl(definition, value) {
      const container = document.createElement("div");
      container.className = "editor-choices";
      const albumSelector = definition.type === "album_selector";
      const multiple = definition.type === "multi_choice" || albumSelector;
      container.setAttribute("role", "group");
      const selected = new Set(multiple ? (value ?? []) : (value ? [value] : []));
      const selectedOrder = [...selected];
      const buttons = [];
      /** Отображает выбранное состояние всех вариантов. */
      const update = () => {
        for (const button of buttons) {
          button.setAttribute("aria-pressed", String(selected.has(button.value)));
        }
      };
      const choices = albumSelector
        ? Object.entries(this.data.albums).map(([id, album]) => ({ value: id, label: album.display_name }))
        : definition.choices.map((choice) => ({ value: choice, label: choice }));
      for (const choice of choices) {
        const button = this.button(choice.label, `${definition.display_name}: ${choice.label}`, () => {
          const value = choice.value;
          if (multiple) {
            if (selected.has(value)) {
              selected.delete(value);
              selectedOrder.splice(selectedOrder.indexOf(value), 1);
            } else {
              selected.add(value);
              selectedOrder.push(value);
            }
          } else {
            selected.clear();
            selected.add(value);
          }
          update();
        });
        button.value = choice.value;
        buttons.push(button);
        container.append(button);
      }
      update();
      return {
        element: container,
        get: () => albumSelector ? selectedOrder.filter((id) => selected.has(id))
          : multiple ? definition.choices.filter((choice) => selected.has(choice))
          : (selected.values().next().value ?? null),
        clear: () => { selected.clear(); selectedOrder.splice(0); update(); },
      };
    }

    /** Создаёт десять кликабельных звёзд с подсветкой выбранной оценки. */
    ratingControl(value) {
      const container = document.createElement("div");
      container.className = "editor-rating";
      container.setAttribute("role", "group");
      let rating = value ?? null;
      const buttons = [];
      const label = document.createElement("span");
      label.className = "rating-label";
      label.setAttribute("aria-live", "polite");
      /** Обновляет звёзды и доступные подписи текущей оценки. */
      const update = () => {
        label.textContent = `${rating ?? "—"}/10`;
        buttons.forEach((button, index) => {
          button.textContent = index < rating ? "★" : "☆";
          button.classList.toggle("is-filled", index < rating);
          button.setAttribute("aria-pressed", String(index + 1 === rating));
        });
      };
      for (let number = 1; number <= 10; number += 1) {
        const button = this.button("☆", `Оценка ${number} из 10`, () => { rating = number; update(); });
        buttons.push(button);
        container.append(button);
      }
      container.append(label);
      update();
      return {
        element: container,
        get: () => rating,
        clear: () => { rating = null; update(); },
      };
    }

    /** Строит поля в порядке конфигурации, используя русские подписи тегов. */
    build() {
      element("metadata-fields").replaceChildren();
      this.fields = [];
      const filename = this.simpleControl({ type: "string" }, this.data.filename);
      this.filename = filename.element;
      this.filename.required = true;
      this.appendField("filename", "Имя файла", { ...filename, extension: this.data.extension }, false);
      const description = this.simpleControl({ type: "text" }, this.data.description);
      this.description = description.element;
      this.appendField("description", "Описание", description);
      for (const [key, definition] of Object.entries(this.data.definitions)) {
        const value = this.data.tags[key];
        const control = definition.type === "list" ? this.listControl(definition, value)
          : definition.type === "single_choice" || definition.type === "multi_choice" || definition.type === "album_selector" ? this.choiceControl(definition, value)
          : definition.type === "star_rating" ? this.ratingControl(value)
          : definition.type === "bool" ? this.booleanControl(definition, value)
          : this.simpleControl(definition, value);
        this.fields.push({ key, get: control.get });
        this.appendField(key, definition.display_name, control);
      }
    }
  }

  window.MetadataEditor = MetadataEditor;
})();
