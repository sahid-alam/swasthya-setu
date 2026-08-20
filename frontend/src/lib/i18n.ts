/* Hindi and English only — CLAUDE.md §NEVER BUILD caps language scope, and the
   Bhashini voice flow (Tier 2) is separate from this. Patient-facing copy lives
   here so the PWA and the kiosk skin cannot drift apart. */

export type Lang = "HI" | "EN";

const STRINGS = {
  EN: {
    appName: "Swasthya-Setu",
    bookTitle: "Book an appointment",
    chooseDepartment: "Choose a department",
    choosePatient: "Who is this appointment for?",
    availableTimes: "Available times",
    noTimes: "No open appointments in the next week.",
    confirm: "Confirm appointment",
    booking: "Booking…",
    booked: "Appointment confirmed",
    token: "Token",
    withDoctor: "With",
    at: "at",
    myQueue: "My queue position",
    positionLabel: "You are number",
    waitLabel: "Estimated wait",
    minutes: "minutes",
    offlineBanner:
      "You are offline. Your booking is saved and will be sent automatically.",
    pendingCount: "booking waiting to be sent",
    pendingCountPlural: "bookings waiting to be sent",
    syncNow: "Send now",
    synced: "Sent",
    tryAgain: "Try again",
    somethingWrong: "Something went wrong. Your booking has been saved.",
    switchLang: "हिन्दी",
  },
  HI: {
    appName: "स्वास्थ्य-सेतु",
    bookTitle: "अपॉइंटमेंट बुक करें",
    chooseDepartment: "विभाग चुनें",
    choosePatient: "यह अपॉइंटमेंट किसके लिए है?",
    availableTimes: "उपलब्ध समय",
    noTimes: "अगले सप्ताह कोई अपॉइंटमेंट उपलब्ध नहीं है।",
    confirm: "अपॉइंटमेंट पक्का करें",
    booking: "बुक हो रहा है…",
    booked: "अपॉइंटमेंट पक्का हो गया",
    token: "टोकन",
    withDoctor: "डॉक्टर",
    at: "में",
    myQueue: "मेरी बारी",
    positionLabel: "आपका नंबर है",
    waitLabel: "अनुमानित प्रतीक्षा",
    minutes: "मिनट",
    offlineBanner:
      "आप ऑफ़लाइन हैं। आपकी बुकिंग सुरक्षित है और अपने आप भेज दी जाएगी।",
    pendingCount: "बुकिंग भेजी जानी है",
    pendingCountPlural: "बुकिंग भेजी जानी हैं",
    syncNow: "अभी भेजें",
    synced: "भेज दिया गया",
    tryAgain: "फिर कोशिश करें",
    somethingWrong: "कुछ गड़बड़ हुई। आपकी बुकिंग सुरक्षित रखी गई है।",
    switchLang: "English",
  },
} as const;

export type Key = keyof (typeof STRINGS)["EN"];

export const t = (lang: Lang, key: Key): string =>
  STRINGS[lang][key] ?? STRINGS.EN[key];

const LANG_KEY = "setu.lang";
export const getLang = (): Lang =>
  (localStorage.getItem(LANG_KEY) as Lang) || "HI";
export const setLang = (l: Lang) => localStorage.setItem(LANG_KEY, l);

/** Times in the patient's script. Hindi uses Devanagari digits nowhere in practice —
 *  Indian Hindi UIs show Latin digits — so only the month/word parts localise. */
export function formatWhen(iso: string, lang: Lang): string {
  const d = new Date(iso);
  return d.toLocaleString(lang === "HI" ? "hi-IN" : "en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
