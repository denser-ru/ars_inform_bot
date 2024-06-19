CREATE TABLE IF NOT EXISTS public.subscriptions (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    chat_id BIGINT,
    query TEXT COLLATE pg_catalog."default" NOT NULL,
    query_vector VECTOR(1024),
    priority INTEGER DEFAULT 3,
    threshold REAL DEFAULT 0.6,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX subscriptions_user_id ON public.subscriptions (user_id); -- Индекс с уникальным именем
CREATE INDEX subscriptions_query_vector_idx ON public.subscriptions 
USING hnsw (query_vector vector_cosine_ops);