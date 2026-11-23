# Lecture assistant evaluation, 2026-11-24T00:08:19

Questions: `C:\Projects\Takamul\ai\lecture-assistant\eval\questions.json` (version 2), 32 questions, 32 evaluated, 0 unavailable.

## Summary

| Measure | Value |
|---|---|
| Decision accuracy (answer or refuse) | 97% |
| Refusal precision | 88% |
| Refusal recall | 100% |
| Hit@1 | 76% |
| Hit@5 | 100% |
| Complete answers | 76% |
| Correct sources (of the answered) | 96% |
| needs_review | 1 |
| Mean time | 12.3 s |
| Unavailable | 0 |
| Chunks from a course not allowed | 0 |

## By question type

| Type | n | Decision | Refusal P / R | Hit@1 | Hit@5 | Complete | Sources | Mean time | Unavailable |
|---|---|---|---|---|---|---|---|---|---|
| text | 12 | 100% | - / - | 75% | 100% | 92% | 100% | 20.5 s | 0 |
| visual | 4 | 100% | - / - | 100% | 100% | 100% | 100% | 17.0 s | 0 |
| cross_language | 5 | 80% | 0% / - | 80% | 100% | 60% | 100% | 7.9 s | 0 |
| not_found | 5 | 100% | 100% / 100% | - | - | - | - | 2.0 s | 0 |
| follow_up | 2 | 100% | - / - | 0% | 100% | 0% | 50% | 4.7 s | 0 |
| colloquial | 2 | 100% | - / - | 100% | 100% | 50% | 100% | 10.8 s | 0 |
| permission | 2 | 100% | 100% / 100% | - | - | - | - | 0.0 s | 0 |

## Questions

| ID | Type | Expected | Got | Rank | Complete | Cited OK | Time | Answer |
|---|---|---|---|---|---|---|---|---|
| T01 | text | answered | answered | 2 | no | yes | 3.4 s | تعتمد صيغة standard error (الخطأ المعياري) على قسمة standard deviation (الانحراف المعياري) للمجتمع على الجذر التربيعي لـ sample size (حجم ال… |
| T02 | text | answered | answered | 1 | yes | yes | 1.3 s | تساوي probability (الاحتمال) لأن يحصل الطالب على درجة بين 350 و 400 حوالي 40.03% [CLT_Chapter2_CLT_2b49d63d854e12d54014f9c86203aec3.pptx، سل… |
| T03 | text | answered | answered | 2 | yes | yes | 13.5 s | There is a 98.3% probability that the plane can carry the 36 boxes from Amman湯 to Cairo within its capacity [CLT_Chapter2_CLT_2b49d63d854e12… |
| T04 | text | answered | answered | 2 | yes | yes | 1.8 s | عندما تم أخذ عينة عشوائية من خمسة متقاعدين، كانت النتيجة للسсем عينة أو متوسط العينة x̄ للمجموعة الأولى هي 67.2 years [CLT_Chapter2_CLT_2b49… |
| T05 | text | answered | answered | 1 | yes | yes | 2.7 s | تتحقق Integrity (السلامة) باستخدام Hashing algorithms مثل SHA-256 والتوقيعات الرقمية digital signatures وإجراءات التحكم الصارم في التغيير st… |
| T06 | text | answered | answered | 1 | yes | yes | 84.1 s | حدث الهجوم المذكور في عام 2021 [Ch 1_5e7cf8dcf4cde52e80cc9670ce63e3a6.pdf، صفحة 18]. تم دفع فدية بقيمة 4.4 مليون دولار في هذه القضية [Ch 1_5… |
| T07 | text | answered | answered | 1 | yes | yes | 5.6 s | يعتبر SolarWinds Attack مثالاً كلاسيكياً على Supply Chain Attack [Ch 1_5e7cf8dcf4cde52e80cc9670ce63e3a6.pdf، صفحة 16]. |
| T08 | text | answered | answered | 1 | yes | yes | 7.1 s | في فترة الحواسيب الكبيرة أو ما تعرف بـ Mainframe Era، كان التركيز منصباً على physical security (الأمن المادي) وAccess Control [Ch 1_5e7cf8dc… |
| T09 | text | answered | answered | 1 | yes | yes | 100.0 s | في عام 2022، كان هناك ما يقدر بنحو 20 million new cancer cases حالة جديدة من السرطان و9.7 million cancer deaths حالة وفاة بسبب السرطان في جم… |
| T10 | text | answered | answered | 1 | yes | yes | 2.4 s | نعم، ترتبط بعض أنواع العدوى مثل human papillomavirus (فيروس الورم الحليمي البشري) والتهاب الكبد B وC بأسرطان معين [Cancer_Awareness_English.… |
| T11 | text | answered | answered | 1 | yes | yes | 15.2 s | يعرف طباق السلب (طباق السلب) بأنه ذكر كلمة ونقيضها عن طريق النفي أو الإثبات [Copy of qaadh-altbaq-walmqablh-fy-allghh-alarbyh.pptx (2).pptx،… |
| T12 | text | answered | answered | 1 | yes | yes | 8.7 s | بلغ عدد الطلبة ذوي الإعاقة المتقدمين المستوفين للمعايير في العام الجامعي 2021/2022 ما هو 201 [تكامل CampusBridge.pdf، صفحة 3]. وبلغت نسبة ال… |
| V01 | visual | answered | answered | 1 | yes | yes | 50.6 s | تظهر في Normal curve (منحنى طبيعي) نسبة مئوية قدرها 13.6% على المنطقة الواقعة بين 1σ و 2σ [CLT_Chapter2_CLT_2b49d63d854e12d54014f9c86203aec3… |
| V02 | visual | answered | answered | 1 | yes | yes | 8.3 s | حصلت Reem Basel في مادة Mathematics على 98 [Student_Grades_and_Chart.xlsx، ورقة 1]. |
| V03 | visual | answered | answered | 1 | yes | yes | 2.1 s | يتم القطاف والعصر في فصل الخريف وبداية الشتاء [بحث_عن_شجرة_الزيتون.docx، صفحة 3]. |
| V04 | visual | answered | answered | 1 | yes | yes | 6.9 s | لا، في جدول المقارنة مع المنافسين، لا يحتوي Note Depot على ميزة تحويل الكلام إلى نص [تكامل CampusBridge.pdf، صفحة 7]. |
| A01 | cross_language | answered | answered | 1 | yes | yes | 7.3 s | عندما يكون sample size (حجم العينة) كبيراً، فإن standard error (الخطأ المعياري) يكون صغيراً وتكون sample means (متوسطات العينات) متجمعة بإحك… |
| A02 | cross_language | answered | answered | 1 | yes | yes | 14.3 s | نكتشف القيم المتطرفة عبر جمع مجموعة البيانات وحساب متوسطها وstandard deviation (الانحراف المعياري) الخاص بها، ثم استخدامها لحساب z-score (ال… |
| A03 | cross_language | answered | answered | 2 | yes | yes | 12.9 s | يُحقق Availability (التوافر) من خلال ضمان أن المعلومات والأنظمة التي تعالجها متاحة وقابلة للاستخدام من قبل المستخدمين المصرح لهم كلما احتاجو… |
| A04 | cross_language | answered | not_found | 1 | no | no | 0.9 s | هذا غير موجود في محاضرات المساق. |
| A05 | cross_language | answered | answered | 1 | no | yes | 4.0 s | يُعرف Insider Threats (التهديدات الداخلية) بأنه خطر أمني ينشأ من داخل المنظمة المستهدفة [Ch 1_5e7cf8dcf4cde52e80cc9670ce63e3a6.pdf، صفحة 20]… |
| N01 | not_found | not_found | not_found | - | - | - | 6.7 s | هذا غير موجود في محاضرات المساق. |
| N02 | not_found | not_found | not_found | - | - | - | 0.0 s | هذا غير موجود في محاضرات المساق. |
| N03 | not_found | not_found | not_found | - | - | - | 1.3 s | هذا غير موجود في محاضرات المساق. |
| N04 | not_found | not_found | not_found | - | - | - | 2.0 s | هذا غير موجود في محاضرات المساق. |
| N05 | not_found | not_found | not_found | - | - | - | 0.0 s | هذا غير موجود في محاضرات المساق. |
| F01 | follow_up | answered | answered | 2 | no | yes | 7.9 s | تم قسمة سعة الطائرة Plane capacity البالغة 2,630 lb على 36 صندوقاً لتمثل الحد الأقصى لمتوسط الوزن لكل صندوق xcrit [CLT_Chapter2_CLT_2b49d63d… |
| F02 | follow_up | answered | needs_review | 2 | no | no | 1.5 s | تمثل Confidentiality (السرية) أحد مبادئ CIA Triad (ثالوث أمن المعلومات)، ويُعد مثال الاختراق لها قيام هاكر بسرقة قاعدة بيانات تحتوي على أسما… |
| D01 | colloquial | answered | answered | 1 | yes | yes | 12.6 s | يُعرف طباق الإيجاب بأنه الجمع بين كلمة وضدها دون تغيير في الصيغة، أي أن الكلمتين موجبتان [Copy of qaadh-altbaq-walmqablh-fy-allghh-alarbyh.p… |
| D02 | colloquial | answered | answered | 1 | no | yes | 9.1 s | يعتبر Information Security (InfoSec) المظلة الأوسع ويشمل حماية جميع أشكال المعلومات الرقمية والمادية والفكرية من خلال نهج شامل يضم الأفراد و… |
| P01 | permission | not_found | not_found | - | - | - | 0.0 s | هذا غير موجود في محاضرات المساق. |
| P02 | permission | not_found | not_found | - | - | - | 0.0 s | هذا غير موجود في محاضرات المساق. |

## Failures

- **T01** (text): missing: σ / √n; population standard deviation | standard deviation of the whole population
- **A04** (cross_language): refused before the model: best similarity 0.668, best coverage 0.5, below the thresholds
- **A05** (cross_language): missing: phishing
- **F01** (follow_up): missing: 73.06
- **F02** (follow_up): missing: Denial-of-Service; flooding | traffic | إغراق; correct page not cited (cited: Ch 1_5e7cf8dcf4cde52e80cc9670ce63e3a6.pdf page 4, Ch 1_5e7cf8dcf4cde52e80cc9670ce63e3a6.pdf page 5)
- **D02** (colloquial): missing: subset; broadest umbrella | all forms of information; encryption | data masking | data loss prevention
