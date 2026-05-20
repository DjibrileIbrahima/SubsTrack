import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'

const MONTHLY_FACTOR = {
  weekly: 4.33,
  biweekly: 2.17,
  monthly: 1,
  quarterly: 1 / 3,
  yearly: 1 / 12,
}

const COLORS = ['#3b82f6', '#10b981', '#8b5cf6', '#f59e0b', '#ef4444', '#14b8a6', '#f97316']

export default function CategoryChart({ subscriptions = [] }) {
  if (subscriptions.length < 2) return null

  const catMap = subscriptions.reduce((acc, s) => {
    const cat = s.category || 'Other'
    const monthly = (s.amount || 0) * (MONTHLY_FACTOR[s.frequency] || 1)
    acc[cat] = (acc[cat] || 0) + monthly
    return acc
  }, {})

  const data = Object.entries(catMap)
    .map(([name, value]) => ({ name, value: Math.round(value * 100) / 100 }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 7)

  if (data.length <= 1) return null

  const chartHeight = data.length * 36 + 24

  return (
    <div className="chart-wrap">
      <h3 className="section-title">By Category</h3>

      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart
          data={data}
          layout="vertical"
          barSize={14}
          margin={{ left: 8, right: 28, top: 4, bottom: 0 }}
        >
          <XAxis
            type="number"
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 12, fill: 'var(--text-muted)' }}
            tickFormatter={(v) => `$${Math.round(v)}`}
          />

          <YAxis
            type="category"
            dataKey="name"
            axisLine={false}
            tickLine={false}
            width={88}
            tick={{ fontSize: 12, fill: 'var(--text-muted)' }}
          />

          <Tooltip
            formatter={(value) => [`$${Number(value).toFixed(2)}/mo`, 'Monthly est.']}
            contentStyle={{
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              fontSize: '13px',
            }}
          />

          <Bar dataKey="value" radius={[0, 4, 4, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
