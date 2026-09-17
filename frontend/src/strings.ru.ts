import { strings as en } from "./strings.en";

/** Russian panel copy. English values remain the fallback for future keys. */
export const stringsRu = {
  ...en,
  masthead: { ...en.masthead, title: "Тибиальный чехол", subtitle: "Косметическая оболочка, печать под заказ", specLabel: "Параметры", specSeparator: " · " },
  presets: { heading: "Начать с" },
  groups: { limb: "Конечность", section: "Сечение", shell: "Оболочка", pattern: "Ячеистое поле", relief: "Рельеф", mask: "Расположение", finish: "Отделка" },
  params: {
    ...en.params,
    length: "Длина", knee_diameter: "Колено", ankle_diameter: "Лодыжка", calf_bulge: "Икра", calf_position: "Высота икры", posterior_bias: "Икра назад",
    ovality: "Овальность", section_squareness: "Прямоугольность", twist: "Скручивание", wall_thickness: "Толщина стенки", pattern_density: "Плотность",
    density_gradient: "Градиент", irregularity: "Неравномерность", anisotropy: "Растяжение", flow_angle: "Наклон", corner_radius: "Углы",
    strut_width: "Перемычка", motif_fill: "Заполнение", motif_rotation: "Поворот", motif_rotation_jitter: "Разброс поворота",
    motif_scale_jitter: "Разброс размера", motif_smoothing: "Сглаживание", threshold_bias: "Порог", relief_depth: "Глубина",
    mask_v_from: "От", mask_v_to: "До", mask_u_center: "Направление", mask_u_width: "Ширина", mask_feather: "Мягкость", facet_scale: "Размер граней",
  },
  paramsImage: { pattern_density: "Размер мотива", irregularity: "Рассеивание" },
  units: { ...en.units, deg: "°", "g/cm³": "г/см³" } as Record<string, string>,
  choices: {
    operation: { label: "Операция", options: { cut: "Сквозной вырез", emboss: "Рельеф наружу", engrave: "Рельеф внутрь", none: "Гладкая" } },
    hole_shape: { label: "Форма отверстия", options: { cells: "Ячейки", image: "Изображение" } },
    relief_profile: { label: "Форма", options: { dome: "Купол", ridge: "Гребень", bevel: "Фаска" } },
    mask_mode: { label: "Расположение узора", options: { full: "Везде", band: "Полоса", panel: "Панель", stripes: "Полосы" } },
    finish: { label: "Затенение", options: { flat: "Плоское", gradient: "Градиент", faceted: "Гранёное" } },
  },
  toggles: { mask_mirror: "Повторить с другой стороны", split_halves: "Разделить пополам", motif_align_flow: "Повернуть по наклону", motif_invert: "Инвертировать вырез" },
  motif: { ...en.motif, choose: "Выбрать изображение", replace: "Выбрать другое", hint: "PNG, JPEG, WebP или SVG. До 8 МБ.", previewLabel: "Просмотр", reading: "Читаем изображение", unreadable: "Этот файл не удалось прочитать", empty: "В изображении ничего не найдено", specTag: "ИЗОБРАЖЕНИЕ" },
  material: { heading: "Материал", secondHeading: "Второй цвет", polymerSeparator: " · ", densityUnit: "г/см³" },
  readout: { mass: "Вес", massUnit: "г", saving: "Легче обычного", savingUnit: "%", added: "Тяжелее обычного", addedUnit: "г", holes: "Ячейки", triangles: "" },
  notes: { heading: "Заметки" },
  actions: { download: "Скачать для печати", working: "Подготовка", formatSecondary: "STL", formatHint: "3MF сохраняет топологию и цвет. STL нужен для совместимости." },
  status: { computing: "Пересчитываем", offline: "Сервис модели недоступен", draft: "Черновая сетка" },
} as unknown as typeof en;
