# הגדרה חד-פעמית - Dr. Rofe Autonomous PR Agent

חיבור כל נכס נעשה **פעם אחת**: יוצרים טוקן/מפתח רשמי מהפלטפורמה (בקישור הישיר
למטה), ומוסיפים אותו כ-Secret ברפו. אחרי זה הכל רץ אוטומטית, בלי צורך בהתחברות ידנית.

**איפה מוסיפים Secrets (קישור ישיר):**
https://github.com/guyrofe-create/dr-rofe-pr-agent/settings/secrets/actions
→ "New repository secret" → שם + ערך → Save.

לא נשתמש בשום סיסמה אישית שלך לאף פלטפורמה - רק בטוקנים רשמיים שניתנים לביטול
בכל רגע מצד הפלטפורמה עצמה, בלי לסכן את החשבון.

---

## Tier 1 - פרסום אוטומטי מלא (יש API רשמי)

### Facebook (עמוד עסקי בלבד בפיילוט)
1. https://developers.facebook.com/apps/creation/ → צור אפליקציה (סוג: Business)
2. בתוך האפליקציה → Add Product → "Facebook Login for Business" → הרשאות: `pages_manage_posts`, `pages_read_engagement`
3. https://developers.facebook.com/tools/explorer/ → בחר את האפליקציה שלך, בחר Page = drguyrofe → Generate Access Token → המר ל-long-lived (Access Token Debugger: https://developers.facebook.com/tools/debug/accesstoken/)
4. חבר חשבון Instagram מקצועי לעמוד והענק לאפליקציה הרשאות
   `instagram_basic` ו־`instagram_content_publish`.

Secrets: `FACEBOOK_PAGE_ID`, `FACEBOOK_PAGE_TOKEN`, `INSTAGRAM_BUSINESS_ID`
(אינסטגרם דורש גם תמונה בכל פוסט - ראה `SOCIAL_IMAGE_URL` למטה)

### Twitter / X
1. https://developer.twitter.com/en/portal/dashboard → צור פרויקט + אפליקציה
2. בתוך האפליקציה → User authentication settings → הפעל, הרשאות Read+Write
3. בטאב "Keys and tokens" (של אותה אפליקציה) → הפק API Key/Secret ו-Access Token/Secret

Secrets: `TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET`

### Tumblr (drguyrofe.tumblr.com)
1. https://www.tumblr.com/oauth/apps → Register application → קבל Consumer Key/Secret
2. https://api.tumblr.com/console/calls/user/info → מתחבר עם ה-Consumer Key שלך ומפיק OAuth Token/Secret ישירות בדפדפן (העתק מהתגובה)

Secrets: `TUMBLR_CONSUMER_KEY`, `TUMBLR_CONSUMER_SECRET`, `TUMBLR_OAUTH_TOKEN`, `TUMBLR_OAUTH_SECRET`, `TUMBLR_BLOG_NAME=drguyrofe`

### Telegram (אם יש ערוץ)
1. https://t.me/BotFather → `/newbot` → קבל טוקן
2. הוסף את הבוט כמנהל לערוץ שלך (מתוך אפליקציית טלגרם)

Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID` (לדוגמה `@drguyrofe`)

### Blogger (drguyrofe.blogspot.com)
1. https://console.cloud.google.com/projectcreate → צור פרויקט
2. https://console.cloud.google.com/apis/library/blogger.googleapis.com → הפעל "Blogger API v3" (ודא שהפרויקט החדש נבחר למעלה)
3. https://console.cloud.google.com/apis/credentials → Create Credentials → OAuth client ID → Application type: Desktop app → קבל Client ID + Secret
4. https://developers.google.com/oauthplayground/ → לחץ על גלגל השיניים ⚙️ למעלה מימין → "Use your own OAuth credentials" → הזן את ה-Client ID/Secret → משמאל הדבק Scope: `https://www.googleapis.com/auth/blogger` → Authorize APIs → Exchange authorization code for tokens → העתק Refresh token
5. https://www.blogger.com/ → היכנס לבלוג → Settings → תחת "Blog tools" תמצא את ה-Blog ID בכתובת ה-URL של לוח הבקרה

Secrets: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN`, `BLOGGER_BLOG_ID`

### Pinterest
1. https://developers.pinterest.com/apps/ → צור אפליקציה → הרשאות `pins:write`, `boards:read`
2. באפליקציה → Generate access token (long-lived)
3. https://www.pinterest.com/ → פתח את הלוח הרלוונטי → ה-Board ID מופיע ב-URL של הלוח

Secrets: `PINTEREST_ACCESS_TOKEN`, `PINTEREST_BOARD_ID` (גם כאן נדרשת תמונה - ראה למטה)

### חבילת צילום אמיתי עם רישיון
לפני האישור המוצר מחפש צילום רלוונטי ב-Wikimedia Commons, מאמת שהוא צילום
אמיתי, בודק התאמה לנושא ולרישיון, ושומר את המקור והייחוס. מכל צילום מאושר
נוצרים חיתוכי hero, landscape, square ו-portrait, עם ALT נגיש שמכיל פעם אחת
את שם הלקוח ואת נושא המאמר.

אין במוצר מסלול ליצירת תמונות ב-AI ואין מסלול שממשיך לאישור בלי תמונה.
`OPENAI_API_KEY` משמש כרגע רק לתכנון שאילתות ולבדיקת התאמת צילום קיים; החיפוש
אינו מייצר תמונות. Instagram מקבל רק חבילת צילום ריבועית שאושרה במפורש.
TikTok נשאר בשליטת בעל החשבון והמוצר אינו מפרסם בו.

---

## Tier 2 - ניטור בלבד (Google + AI)

### דירוג בגוגל (Google Custom Search API)
1. https://console.cloud.google.com/apis/library/customsearch.googleapis.com → הפעל → https://console.cloud.google.com/apis/credentials → Create Credentials → API key
2. https://programmablesearchengine.google.com/controlpanel/all → Add → הפעל "Search the entire web" → לאחר היצירה, לך ל-Setup ותעתיק Search engine ID (cx)

Secrets: `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_CX`

### ביקורות גוגל ביזנס (Google Places API)
1. https://console.cloud.google.com/apis/library/places-backend.googleapis.com → הפעל → https://console.cloud.google.com/apis/credentials → Create Credentials → API key
2. https://developers.google.com/maps/documentation/places/web-service/place-id#find-id — יש שם כלי חיפוש אינטראקטיבי: הקלד "דר גיא רופא" ותקבל את ה-Place ID ישירות

Secrets: `GOOGLE_PLACES_API_KEY`, `GOOGLE_PLACE_ID`

### נוכחות ב-AI (ChatGPT)
כבר קיים - `OPENAI_API_KEY` (אותו טוקן שכבר מוגדר לפרסום ב-Medium).

### YouTube
אין API רשמי ל"פרסום" תוכן טקסטואלי (רק העלאת וידאו). לא כלול כרגע - בעתיד
ניטור צפיות/מנויים אפשרי עם מפתח פשוט מ-https://console.cloud.google.com/apis/library/youtube.googleapis.com

### Google Business Profile
הקוד מוכן לפרסום פוסט מידע קצר מסוג `STANDARD`, עם תמונה ציבורית וכפתור
`LEARN_MORE` לעמוד הקנוני. כל הטקסט, התמונה והקישור נכללים בחבילת P7
המדויקת; אין עריכת שעות, שירותים, זמינות, פרטי מרפאה או קביעת תורים.

1. יש להגיש ל-Google בקשת Basic API Access עבור פרויקט
   `reputation-agent-503515` (מספר `236033131361`).
2. לאחר האישור יש לוודא שהמכסה של My Business Account Management API
   גדולה מאפס וש-Google My Business API מופעל.
3. ה-OAuth חייב לכלול `https://www.googleapis.com/auth/business.manage`.
4. אם לחשבון יש מיקום נגיש יחיד, המוצר יגלה אותו בבטחה. אם יש יותר מאחד,
   יש להגדיר את שני ה-Secrets:
   `GOOGLE_BUSINESS_ACCOUNT_ID`, `GOOGLE_BUSINESS_LOCATION_ID`.

המכסה בפרויקט היא כרגע אפס, ולכן הבדיקה והפרסום ייכשלו באופן גלוי עד
ש-Google תאשר את הגישה. אין להשתמש בסיסמה או באוטומציית דפדפן כתחליף ל-API.

---

## Tier 3 - אין API בטוח, פורסם ידנית (30 שניות)

TikTok, Quora, LinkedIn אישי, Flipboard, Slideshare, About.me - אין להן API
פתוח לפרסום, או שדורשות אישור עסקי יקר/מסובך. אוטומציה עם סיסמה אישית שלך
מסוכנת (חשש להשעיית חשבון) ולכן לא ממומשת.

במקום זה: כל הרצה יוצרת קובץ `social_drafts/<תאריך>.md` ברפו, עם טקסט מוכן
להדבקה לכל פלטפורמה + checklist. העתק-הדבק לוקח כ-30 שניות ליום פרסום.

Podcasts (Apple/Spotify) מסונכרנים אוטומטית מה-RSS של הפודקאסט - אין צורך בפעולה נוספת.

---

## מה קורה בלי אף Secret?

כלום לא נשבר. כל מודול בודק את עצמו ומדלג בשקט אם אין לו את מה שהוא צריך -
אפשר להוסיף פלטפורמות אחת-אחת, בכל קצב שנוח לך.

---

## מה כבר בנוי ורץ ברפו עכשיו

- `scripts/daily_run.py` - יוצר טיוטת מאמר רפואי לבדיקה, שני/רביעי/שישי 09:00; הטיוטה מאושרת ומתפרסמת מתוך דשבורד המוניטין
- `scripts/social_run.py` - הפצה לרשתות חברתיות, אותם ימים 10:00 (מדלג על כל פלטפורמה לא מוגדרת)
- `scripts/monitor_run.py` - ניטור יומי (05:00): דירוג גוגל, נוכחות ב-AI, בריאות טוקנים, ביקורות - מדווח כ-GitHub Issue חדש בכל ריצה
- `.github/workflows/social_publish.yml`, `.github/workflows/monitor.yml` - כבר פעילים ברפו

כל הקוד עבר אימות: py_compile על כל קובץ, אימות YAML, ובדיקת import מלאה.

**רפו:** https://github.com/guyrofe-create/dr-rofe-pr-agent
**היסטוריית Issues (דוחות ניטור):** https://github.com/guyrofe-create/dr-rofe-pr-agent/issues
