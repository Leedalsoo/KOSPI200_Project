# Contract Multiplier and Tick-Size Source Proposal — Draft

작성일: 2026-10-14  
상태: 초안 / 값 UNSET / 사용자 승인 대기 / 거래 사용 금지

## Current finding
- The KIS master row does not expose an authoritative contract-multiplier field in the captured source.
- Existing code constants 250000 and 50000 are not treated as authoritative.
- No multiplier or tick-size value is enabled by this proposal. Runtime config must remain null/UNSET until source and approval state are explicit.

## Proposed source hierarchy (requires user decision)
1. First preference: an official KIS contract-specification/API field that explicitly identifies product multiplier and tick size.
2. If KIS does not publish these product rules, candidate alternative: official exchange product-rule documentation used only as a contract-specification source, not as runtime market data, daily prices, option master or holiday authority. This alternative is a policy exception and requires explicit user approval before values are entered.
3. Validation: cross-check observable KIS read-only account/valuation fields and known product-spec values without storing account amounts. An account mismatch or missing valuation field leaves values UNSET.

## Proposed config schema
- product_type -> contract_multiplier: null
- product_type -> tick_size: null
- source_url: null until official source is confirmed
- source_document_version: null
- approved_by_user: false
- approval_reference: null
- validated_at: null
- source_hash: null

## Questions for user
1. If KIS does not expose multiplier/tick, may official exchange product rules be used solely as the contract-specification authority (not runtime market data)? Default recommendation: YES, but do not fill any values until the exact official document is cited and you separately approve the concrete values.
2. Until that decision and source validation, all quantity conversion, PnL/greeks monetary scaling and risk checks that require multiplier/tick must remain BLOCKED/UNSET.

## Account inquiry finding
- The local configuration checks indicated VTS mode, VTS app credentials present, an 8-digit account number starting with 6, and product code 03; no explicit VTS-specific account-number key was present. KIS Developers states VTS mock account numbers starting with 6 are futures/options accounts.
- One read-only balance request returned HTTP 200, rt_cd=1, msg_cd=90070000. The response msg_cd was 90070000; account/user/appkey association could not be confirmed, and msg1 was not legible in the saved text encoding. KIS Developers identifies this as a mock account ID/user-information mismatch, often related to an HTS ID change or live/mock account confusion. KIS Developers public FAQ identifies 90070000 as a VTS mock account ID/user-information mismatch: https://apiportal.koreainvestment.com/. Account identity could not be confirmed.
- No account amount or account number was recorded. No orderable query was attempted after the balance failure. No margin query was attempted because a VTS-supported margin TR ID was not confirmed. No retries were made.
- User confirmation required: Is the configured account number a VTS domestic futures/options virtual account associated with the configured VTS app key and product code 03? Yes/No. Default recommendation: NO API follow-up until the account association is verified outside the failed response.
