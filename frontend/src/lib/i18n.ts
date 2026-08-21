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
    seeMyPlace: "See my place in line",
    peopleAhead: "people ahead of you",
    onePersonAhead: "1 person ahead of you",
    nobodyAhead: "You are first in line",
    yourTurn: "It is your turn",
    yourTurnHelp: "Please go in to see the doctor now.",
    beingMoved: "We are moving this appointment",
    beingMovedHelp:
      "The doctor is not available. We will send you the new time.",
    checkedIn: "You have arrived",
    confirmed: "Confirmed",
    noQueue: "No appointments yet",
    noQueueCopy: "Once you book, your place in line appears here.",
    alsoBooked: "Your other appointments",
    waitIsEstimate:
      "This is an estimate. It changes as the doctor sees people.",
    refresh: "Check again",
    bookAnother: "Book another appointment",
    backToBook: "Book",
    offlineBanner:
      "You are offline. Your booking is saved and will be sent automatically.",
    pendingCount: "booking waiting to be sent",
    pendingCountPlural: "bookings waiting to be sent",
    syncNow: "Send now",
    synced: "Sent",
    tryAgain: "Try again",
    somethingWrong: "Something went wrong. Your booking has been saved.",
    switchLang: "हिन्दी",
    signIn: "Sign in",
    phoneLabel: "Your mobile number",
    emailLabel: "Your email address",
    useEmail: "Use email instead",
    usePhone: "Use my mobile number instead",
    sendCode: "Send me a code",
    codeLabel: "Enter the 6-digit code",
    verify: "Continue",
    codeSent: "If that contact is registered, we have sent it a code.",
    codeByCall: "You will receive a call with your code. Answer and listen.",
    codeBySms: "Your code is on its way by SMS.",
    codeByEmail: "Check your inbox, and your spam folder the first time.",
    codeInTelegram: "Linked Telegram? Check there first.",
    codeWrong: "That code is wrong or has expired.",
    changeNumber: "Use a different contact",
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
    seeMyPlace: "मेरी बारी देखें",
    peopleAhead: "लोग आपसे आगे हैं",
    onePersonAhead: "1 व्यक्ति आपसे आगे है",
    nobodyAhead: "आप सबसे पहले हैं",
    yourTurn: "आपकी बारी है",
    yourTurnHelp: "कृपया अब डॉक्टर के पास जाएँ।",
    beingMoved: "यह अपॉइंटमेंट बदला जा रहा है",
    beingMovedHelp: "डॉक्टर उपलब्ध नहीं हैं। नया समय हम आपको भेजेंगे।",
    checkedIn: "आप पहुँच गए हैं",
    confirmed: "पक्का हो गया",
    noQueue: "अभी कोई अपॉइंटमेंट नहीं",
    noQueueCopy: "बुक करते ही आपकी बारी यहाँ दिखेगी।",
    alsoBooked: "आपके अन्य अपॉइंटमेंट",
    waitIsEstimate: "यह अनुमान है। डॉक्टर के देखने के साथ यह बदलता रहता है।",
    refresh: "फिर देखें",
    bookAnother: "और अपॉइंटमेंट बुक करें",
    backToBook: "बुक करें",
    offlineBanner:
      "आप ऑफ़लाइन हैं। आपकी बुकिंग सुरक्षित है और अपने आप भेज दी जाएगी।",
    pendingCount: "बुकिंग भेजी जानी है",
    pendingCountPlural: "बुकिंग भेजी जानी हैं",
    syncNow: "अभी भेजें",
    synced: "भेज दिया गया",
    tryAgain: "फिर कोशिश करें",
    somethingWrong: "कुछ गड़बड़ हुई। आपकी बुकिंग सुरक्षित रखी गई है।",
    switchLang: "English",
    signIn: "साइन इन करें",
    phoneLabel: "आपका मोबाइल नंबर",
    emailLabel: "आपका ईमेल पता",
    useEmail: "ईमेल का उपयोग करें",
    usePhone: "मोबाइल नंबर का उपयोग करें",
    sendCode: "मुझे कोड भेजें",
    codeLabel: "6 अंकों का कोड डालें",
    verify: "आगे बढ़ें",
    codeSent: "अगर वह संपर्क पंजीकृत है, तो हमने उस पर कोड भेज दिया है।",
    codeByCall: "आपको कोड बताने के लिए कॉल आएगी। कॉल उठाकर सुनें।",
    codeBySms: "आपका कोड SMS से आ रहा है।",
    codeByEmail: "अपना ईमेल देखें — पहली बार स्पैम फ़ोल्डर भी देखें।",
    codeInTelegram: "अगर आपने टेलीग्राम जोड़ा है, तो पहले वहाँ देखें।",
    codeWrong: "यह कोड ग़लत है या समय समाप्त हो गया है।",
    changeNumber: "दूसरा संपर्क इस्तेमाल करें",
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
