select * from {{ ref('a') }} union all select * from {{ ref('b') }}
