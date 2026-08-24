# Project Specific Directives & Guidelines

## Device-Specific Layout & Formatting Scope Rules

1. **PC/Desktop Specific Directives ("PC用", "ブラウザ用")**:
   - When the user specifies fixes/changes for PC/Desktop ("PC用" or "ブラウザ用"), strictly scope all layout and formatting modifications to PC desktop screens (`@media (min-width: 769px)`).
   - NEVER alter or affect mobile layout or styles when fulfilling a PC-specific request.

2. **Mobile/Smartphone Specific Directives ("スマホ用", "モバイル用")**:
   - When the user specifies fixes/changes for Mobile/Smartphone ("スマホ用" or "モバイル用"), strictly scope all layout and formatting modifications to Mobile screens (`@media (max-width: 768px)`).
   - NEVER alter or affect PC desktop layout or styles when fulfilling a Mobile-specific request.

3. **Feature Consistency vs Format Optimization**:
   - Keep underlying data, logic, and features consistent across all devices, but optimize visual layouts, containers, fonts, and interaction formats independently for PC and Mobile to achieve maximum usability on each device.
