// Subscription packages — shared between purchase form, admin panel, and docs.

export const PACKAGES = [
  {
    id: 'manual',
    label: 'راهنمای تعمیرات',
    labelEn: 'Repair Manual',
    icon: 'manual',
    description: 'رویه‌های گام‌به‌گام تعمیر، گشتاورها، تلورانس‌ها و هشدارهای ایمنی کارخانه‌ای.',
    priceNote: 'پایه',
  },
  {
    id: 'parts',
    label: 'کاتالوگ قطعات یدکی',
    labelEn: 'Spare Parts Catalog',
    icon: 'parts',
    description: 'شماره‌فنی اورجینال، کدهای فنی و دیاگرام انفجاری قطعات.',
    priceNote: 'پایه',
  },
  {
    id: 'standard_time',
    label: 'زمان استاندارد تعمیرات',
    labelEn: 'Standard Repair Time (LTS)',
    icon: 'clock',
    description: 'زمان مرجع هر عملیات برای برآورد هزینه و زمان‌بندی تعمیرگاه.',
    priceNote: 'پایه',
  },
  {
    id: 'special_tools',
    label: 'ابزارهای مخصوص',
    labelEn: 'Special Service Tools',
    icon: 'wrench',
    description: 'فهرست ابزارهای ویژه کارخانه‌ای مورد نیاز هر عملیات.',
    priceNote: 'پایه',
  },
  {
    id: 'full_spec',
    label: 'مشخصات کامل خودرو',
    labelEn: 'Full Vehicle Spec',
    icon: 'catalog',
    description: 'مشخصات فنی کامل مدل، آپشن‌ها و پیکربندی.',
    priceNote: 'افزودنی',
  },
];

export const BASE_PACKAGE_IDS = ['manual', 'parts', 'standard_time', 'special_tools'];
export const ALL_PACKAGE_IDS = [...BASE_PACKAGE_IDS, 'full_spec'];

export const PACKAGE_MAP = Object.fromEntries(PACKAGES.map((p) => [p.id, p]));

export const ROLES = [
  { id: 'after_sales_manager', label: 'مدیر خدمات پس از فروش', level: 1 },
  { id: 'after_sales_head', label: 'رئیس خدمات پس از فروش', level: 2 },
  { id: 'after_sales_supervisor', label: 'سرپرست خدمات پس از فروش', level: 3 },
  { id: 'after_sales_specialist', label: 'کارشناس خدمات پس از فروش', level: 4 },
];

export const DEPARTMENT_PRESETS = [
  'خدمات پس از فروش',
  'فنی و مهندسی',
  'گارانتی',
  'پشتیبانی فنی',
];

export const AI_REQUIRES = 'manual';

export function packageLabel(id) {
  return PACKAGE_MAP[id]?.label || id;
}

export function roleWithDepartment(roleLabel, departmentLabel) {
  if (!departmentLabel || departmentLabel === 'خدمات پس از فروش') return roleLabel;
  return roleLabel.replace('خدمات پس از فروش', departmentLabel);
}

export function userHasAiEligibility(packages = []) {
  return packages.includes(AI_REQUIRES);
}

/** Toggle a document chip; full_spec selects all, dropping a base doc drops full_spec. */
export function toggleDocumentSelection(current, docId) {
  const set = new Set(current);
  if (docId === 'full_spec') {
    if (set.has('full_spec')) {
      set.delete('full_spec');
    } else {
      ALL_PACKAGE_IDS.forEach((id) => set.add(id));
    }
  } else if (set.has(docId)) {
    set.delete(docId);
    set.delete('full_spec');
  } else {
    set.add(docId);
    if (BASE_PACKAGE_IDS.every((id) => set.has(id))) {
      set.add('full_spec');
    }
  }
  return [...set];
}

export function selectAllDocuments() {
  return [...ALL_PACKAGE_IDS];
}

export function emptySeatPlanRow() {
  return { role: 'after_sales_specialist', department: 'خدمات پس از فروش', count: 1, note: '' };
}
