CREATE TABLE IF NOT EXISTS portfolios (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
  hash_name text NOT NULL, goods_name text,
  buy_price numeric(10,2) NOT NULL, qty integer DEFAULT 1,
  buy_date date, created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now(),
  UNIQUE(user_id, hash_name)
);
CREATE TABLE IF NOT EXISTS watchlists (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
  hash_name text NOT NULL, target_price numeric(10,2), notes text,
  created_at timestamptz DEFAULT now(), UNIQUE(user_id, hash_name)
);
ALTER TABLE portfolios ENABLE ROW LEVEL SECURITY; ALTER TABLE watchlists ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own_portfolios" ON portfolios FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_watchlists" ON watchlists FOR ALL USING (auth.uid() = user_id);
