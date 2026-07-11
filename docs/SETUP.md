# הגדרה חד-פעמית - Dr. Rofe Autonomous PR Agent

חיבור כל נכס נעשה **פעם אחת**: יוצרים טוקן/מפתח רשמי מהפלטפורמה, ומוסיפים אותו
כ-Secret ברפו. אחרי זה הכל רץ אוטומטית (GitHub Actions), בלי צורך בהתחברות ידנית.

**איפה מוסיפים Secrets:** בכל שלב למטה - github.com/guyrofe-create/dr-rofe-pr-agent
→ Settings → Secrets and variables → Actions → "New repository secret" → שם + ערך.

לא נשתמש בשום סיסמה אישית שלך לאף פלטפורמה - רק בטוקנים רשמיים שניתנים לביטול
בכל רגע מצד הפלטפורמה עצמה, בלי לסכן את החשבון.

---

## Tier 1 - פרסום אוטומטי מלא (יש API רשמי)

### Facebook (עמוד עסקי) + Instagram Business
דורש חשבון Meta Business + עמוד פייסבוק מקושר לאינסטגרם Business.
1. developers.facebook.com → צור אפליקציה (סוג: Business)
2. הוסף מוצר "Facebook Login for Business" ו-Permissions: `pages_manage_posts`, `pages_read_engagement`, `instagram_content_publish`
3. ב-Graph API Explorer → הפק Page Access Token ל-drguyrofe, המר ל-long-lived token (60 יום, מתחדש)
4. מצא את ה-Instagram Business Account ID המקושר לעמוד (דרך `/{page-id}?fields=instagram_business_account`)

Secrets: `FACEBOOK_PAGE_ID`, `FACEBOOK_PAGE_TOKEN`, `INSTAGRAM_BUSINESS_ID`
(אינסטגרם דורש גם תמונה בכל פוסט - ראה `SOCIAL_IMAGE_URL` למטה)

### Twitter / X
1. developer.twitter.com → צור פרויקט + אפליקציה, הרשאות Read+Write
2. Keys and tokens → הפק API Key/Secret ו-Access Token/Secret (עם הרשאת Read+Write)

Secrets: `TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET`

### Tumblr (drguyrofe.tumblr.com)
1. tumblr.com/oauth/apps → Register application
2. קבל Consumer Key/Secret, ואז דרך OAuth flow (או explorer באתר) הפק OAuth Token/Secret

Secrets: `TUMBLR_CONSUMER_KEY`, `TUMBLR_CONSUMER_SECRET`, `TUMBLR_OAUTH_TOKEN`, `TUMBLR_OAUTH_SECRET`, `TUMBLR_BLOG_NAME=drguyrofe`

### Telegram (אם יש ערוץ)
1. פתח שיחה עם @BotFather בטלגרם → `/newbot` → קבל טוקן
2. הוסף את הבוט כמנהל לערוץ שלך

Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID` (לדוגמה `@drguyrofe`)

### Blogger (drguyrofe.blogspot.com)
1. console.cloud.google.com → צור פרויקט → הפעל "Blogger API v3"
2. Credentials → צור OAuth Client ID (Desktop app) → קבל Client ID + Secret
3. עבור ל-developers.google.com/oauthplayground → בהגדרות (⚙️) הזן את ה-Client ID/Secret שלך → בחר Scope `https://www.googleapis.com/auth/blogger` → Authorize → Exchange → העתק את ה-Refresh Token
4. מצא את ה-Blog ID במסך ההגדרות של הבלוג ב-blogger.com

Secrets: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN`, `BLOGGER_BLOG_ID`

### Pinterest
1. developers.pinterest.com → צור אפליקציה → הרשאות `pins:write`, `boards:read`
2. הפק Access Token (long-lived) ומצא את ה-Board ID של הלוח הרלוונטי

Secrets: `PINTEREST_ACCESS_TOKEN`, `PINTEREST_BOARD_ID` (גם כאן נדרשת תמונה - ראה למטה)

### תמונה משותפת ל-Instagram + Pinterest (אופציונלי)
Secret: `SOCIAL_IMAGE_URL` - קישור URL ציבורי לתמונה קבועה (למשל לוגו/תמונת פרופיל
מהאתר). בלי זה שני אלה ידלגו אוטומטית מבלי להיכשל.

---

## Tier 2 - ניטור בלבד (Google + AI)

### דירוג בגוגל (Google Custom Search API)
1. console.cloud.google.com → הפעל "Custom Search API" → צור API Key
2. programmablesearchengine.google.com → צור מנוע חיפוש חדש שסורק את כל האינטרנט → העתק Search Engine ID (cx)

Secrets: `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_CX`

### ביקורות גוגל ביזנס (Google Places API)
1. console.cloud.google.com → הפעל "Places API" → צור API Key
2. מצא את ה-Place ID של העסק דרך developers.google.com/maps/documentation/places/web-service/place-id (חפש "דר גיא רופא")

Secrets: `GOOGLE_PLACES_API_KEY`, `GOOGLE_PLACE_ID`

### נוכחות ב-AI (ChatGPT)
כבר קיים - `OPENAI_API_KEY` (אותו טוקן שכבר מוגדר לפרסום ב-Medium).

### YouTube
אין API רשמי ל"פרסום" תוכן טקסטואלי (רק העלאת וידאו). בשלב זה לא כלול -
אם תרצה בעתיד ניטור צפיות/מנויים, זה אפשרי עם `YOUTUBE_API_KEY` פשוט.

### Google Business - פרסום אוטומטי
גוגל דורשת אישור שותפות מיוחד (Business Profile API) שלא נגיש לעסק בודד -
לכן רק ניטור ביקורות זמין כרגע, לא פרסום פוסטים.

---

## Tier 3 - אין API בטוח, פורסם ידנית (30 שניות)

הפלטפורמות האלה (TikTok, Quora, LinkedIn אישי, Flipboard, Slideshare, About.me)
אין להן API פתוח לפרסום, או שדורשות אישור עסקי יקר/מסובך. אוטומציה עם
סיסמה אישית שלך מסוכנת (חשש להשעיית חשבון) ולכן לא ממומשת.

במקום זה: כל הרצה יוצרת קובץ `social_drafts/<תאריך>.md` ברפו, עם טקסט מוכן
להדבקה לכל פלטפורמה + checklist. אתה (או מישהו מהצוות) מעתיק-מדביק ב-30
שניות ליום פרסום.

Podcasts (Apple/Spotify) מסונכרנים אוטומטית מה-RSS של הפודקאסט - אין צורך
בפעולה נוספת.

---

## מה קורה בלי אף Secret?

כלום לא נשבר. כל מודול בודק את עצמו ומדלג בשקט אם אין לו את מה שהוא צריך -
אפשר להוסיף פלטפורמות אחת-אחת, בכל קצב שנוח לך.
