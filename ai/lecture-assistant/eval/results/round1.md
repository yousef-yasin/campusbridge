# Lecture assistant evaluation, 2026-11-23T23:50:21

Questions: `C:\Projects\Takamul\ai\lecture-assistant\eval\questions.json` (version 1), 32 questions, 32 evaluated, 0 unavailable.

## Summary

| Measure | Value |
|---|---|
| Decision accuracy (answer or refuse) | 97% |
| Refusal precision | 88% |
| Refusal recall | 100% |
| Hit@1 | 76% |
| Hit@5 | 100% |
| Complete answers | 60% |
| Correct sources (of the answered) | 100% |
| needs_review | 0 |
| Mean time | 7.4 s |
| Unavailable | 0 |
| Chunks from a course not allowed | 0 |

## By question type

| Type | n | Decision | Refusal P / R | Hit@1 | Hit@5 | Complete | Sources | Mean time | Unavailable |
|---|---|---|---|---|---|---|---|---|---|
| text | 12 | 100% | - / - | 75% | 100% | 50% | 100% | 6.4 s | 0 |
| visual | 4 | 100% | - / - | 100% | 100% | 100% | 100% | 10.0 s | 0 |
| cross_language | 5 | 80% | 0% / - | 80% | 100% | 60% | 100% | 6.4 s | 0 |
| not_found | 5 | 100% | 100% / 100% | - | - | - | - | 7.2 s | 0 |
| follow_up | 2 | 100% | - / - | 0% | 100% | 50% | 100% | 11.2 s | 0 |
| colloquial | 2 | 100% | - / - | 100% | 100% | 50% | 100% | 14.0 s | 0 |
| permission | 2 | 100% | 100% / 100% | - | - | - | - | 0.9 s | 0 |

## Questions

| ID | Type | Expected | Got | Rank | Complete | Cited OK | Time | Answer |
|---|---|---|---|---|---|---|---|---|
| T01 | text | answered | answered | 2 | no | yes | 4.6 s | تعتمد صيغة standard error (الخطأ المعياري) على قسمة standard deviation (الانحراف المعياري) للمجتمع على الجذر التربيعي لـ sample size (حجم ال… |
| T02 | text | answered | answered | 1 | no | yes | 2.7 s | تساوي probability (الاحتمال) أن يحصل الطالب على درجة بين 350 و 400 حوالي 40.03% [CLT_Chapter2_CLT_2b49d63d854e12d54014f9c86203aec3.pptx، سلا… |
| T03 | text | answered | answered | 2 | yes | yes | 2.8 s | There is a 98.3% probability that the plane can carry the 36 boxes from Amman to Cairo within its capacity [CLT_Chapter2_CLT_2b49d63d854e12d… |
| T04 | text | answered | answered | 2 | yes | yes | 2.7 s | عندما تم أخذ sample (العينة) من n = 5 retirees، أعطت Mean (متوسط العينة) بقيمة 67.2 years [CLT_Chapter2_CLT_2b49d63d854e12d54014f9c86203aec3… |
| T05 | text | answered | answered | 1 | no | yes | 9.5 s | تتحقق Integrity (السلامة) من خلال عدة تقنيات منها Hashing algorithms (خوارزميات التجزئة) مثل SHA-256، والتوقيعات الرقمية، وإجراءات التحكم ال… |
| T06 | text | answered | answered | 1 | yes | yes | 3.2 s | حدث الهجوم المسمى The Colonial Pipeline Attack في عام (2021) [Ch 1_5e7cf8dcf4cde52e80cc9670ce63e3a6.pdf، صفحة 18]. تم دفع فدية قدرها 4.4 ملي… |
| T07 | text | answered | answered | 1 | no | yes | 13.0 s | يعتبر SolarWinds Attack مثالاً كلاسيكياً على Supply Chain Attack [Ch 1_5e7cf8dcf4cde52e80cc9670ce63e3a6.pdf، صفحة 16]. |
| T08 | text | answered | answered | 1 | no | yes | 13.1 s | في حقبة الأجهزة الرئيسية المذكورة، كان التركيز منصباً على physical security (الأمن المادي) و access control [Ch 1_5e7cf8dcf4cde52e80cc9670ce… |
| T09 | text | answered | answered | 1 | yes | yes | 2.2 s | في عام 2022، كان هناك تقديرات تشير إلى وجود 20 million حالة إصابة جديدة بمرض السرطان و9.7 million حالة وفاة بسبب السرطان في جميع أنحاء العال… |
| T10 | text | answered | answered | 1 | no | yes | 3.9 s | نعم، تشير المعطيات إلى أن بعض الالتهابات مرتبطة بأنواع محددة من السرطان [Cancer_Awareness_English.docx، صفحة 2]. ومن ضمن هذه الالتهابات Huma… |
| T11 | text | answered | answered | 1 | yes | yes | 10.7 s | يعرف طباق السلب بأنه ذكر كلمة ونقيضها عن طريق النفي أو الإثبات [Copy of qaadh-altbaq-walmqablh-fy-allghh-alarbyh.pptx (2).pptx، سلايد 5]. وم… |
| T12 | text | answered | answered | 1 | yes | yes | 8.2 s | بلغ عدد الطلبة ذوي الإعاقة المتقدمين في العام الجامعي 2021/2022 نحو 201 طالباً [تكامل CampusBridge.pdf، صفحة 3]. وتبلغ نسبة المكفوفين والصم … |
| V01 | visual | answered | answered | 1 | yes | yes | 5.7 s | يوضح الشكل Normal curve (منحنى طبيعي) أن النسبة المكتوبة على المنطقة الواقعة بين 1σ و 2σ هي 13.6% [CLT_Chapter2_CLT_2b49d63d854e12d54014f9c8… |
| V02 | visual | answered | answered | 1 | yes | yes | 2.3 s | حصلت Reem Basel في مادة Mathematics على 98 [Student_Grades_and_Chart.xlsx، ورقة 1]. |
| V03 | visual | answered | answered | 1 | yes | yes | 24.0 s | يتم القطاف والعصر في فصل الخريف وبداية الشتاء [بحث_عن_شجرة_الزيتون.docx، صفحة 3]. |
| V04 | visual | answered | answered | 1 | yes | yes | 8.1 s | لا، فبحسب جدول المقارنة مع المنافسين، لا يحتوي Note Depot على ميزة تحويل الكلام إلى نص [تكامل CampusBridge.pdf، صفحة 7]. |
| A01 | cross_language | answered | answered | 1 | yes | yes | 8.9 s | عندما يكون sample size (حجم العينة) كبيرًا، يصبح standard error (الخطأ المعياري) صغيرًا [CLT_Chapter2_CLT_2b49d63d854e12d54014f9c86203aec3.p… |
| A02 | cross_language | answered | answered | 1 | yes | yes | 2.7 s | لنكتشف القيم المتطرفة، نقوم أولاً بجمع مجموعة البيانات وحساب متوسط المجتمع والانحراف المعياري [CLT_Chapter2_CLT_2b49d63d854e12d54014f9c86203… |
| A03 | cross_language | answered | answered | 2 | yes | yes | 12.6 s | يُحقق التوافر أو Availability من خلال Redundant systems (خوادم احتياطية)، وrobust network architecture، وdisaster recovery plans، وحماية ضد … |
| A04 | cross_language | answered | not_found | 1 | no | no | 0.9 s | هذا غير موجود في محاضرات المساق. |
| A05 | cross_language | answered | answered | 1 | no | yes | 6.8 s | يُعرف Insider Threats (التهديد الداخلي) بأنه خطر أمني ينشأ من داخل المنظمة المستهدفة [Ch 1_5e7cf8dcf4cde52e80cc9670ce63e3a6.pdf، صفحة 20]. و… |
| N01 | not_found | not_found | not_found | - | - | - | 10.1 s | هذا غير موجود في محاضرات المساق. |
| N02 | not_found | not_found | not_found | - | - | - | 1.0 s | هذا غير موجود في محاضرات المساق. |
| N03 | not_found | not_found | not_found | - | - | - | 10.5 s | هذا غير موجود في محاضرات المساق. |
| N04 | not_found | not_found | not_found | - | - | - | 13.2 s | هذا غير موجود في محاضرات المساق. |
| N05 | not_found | not_found | not_found | - | - | - | 1.0 s | هذا غير موجود في محاضرات المساق. |
| F01 | follow_up | answered | answered | 2 | yes | yes | 20.2 s | تم قسمة 2,630 لأن سعة الطائرة Plane capacity تبلغ 2,630 lb [CLT_Chapter2_CLT_2b49d63d854e12d54014f9c86203aec3.pptx، سلايد 21]. وتمثل النتيجة… |
| F02 | follow_up | answered | answered | 2 | no | yes | 2.3 s | يتمثل مثال الاختراق لـ Availability (التوافر) في Denial-of-Service (DoS) attacks (هجمات حجب الخدمة) التي تغرق خادم موقع الويب بالمرور، مما ي… |
| D01 | colloquial | answered | answered | 1 | yes | yes | 25.9 s | يُعرف طباق الإيجاب بأنه الجمع بين كلمة وضدها دون تغيير في الصيغة، أي أن الكلمتين موجبتان [Copy of qaadh-altbaq-walmqablh-fy-allghh-alarbyh.p… |
| D02 | colloquial | answered | answered | 1 | no | yes | 2.2 s | يعد Data Security (أمن البيانات) مجموعة فرعية من InfoSec (أمن المعلومات) حيث يركز على حماية البيانات الرقمية في حالة السكون وأثناء النقل وأث… |
| P01 | permission | not_found | not_found | - | - | - | 0.8 s | هذا غير موجود في محاضرات المساق. |
| P02 | permission | not_found | not_found | - | - | - | 0.9 s | هذا غير موجود في محاضرات المساق. |

## Failures

- **T01** (text): missing: population standard deviation | standard deviation of the whole population
- **T02** (text): missing: 0.40033
- **T05** (text): missing: digital signatures; change control
- **T07** (text): missing: 2020
- **T08** (text): missing: 1970s
- **T10** (text): missing: HPV; hepatitis B and C | hepatitis B | hepatitis
- **A04** (cross_language): refused before the model: best similarity 0.667, best coverage 0, below the thresholds
- **A05** (cross_language): missing: phishing
- **F02** (follow_up): missing: flooding | traffic | إغراق
- **D02** (colloquial): missing: subset; broadest umbrella | all forms of information; encryption | data masking | data loss prevention
