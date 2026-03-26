import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

export default function SpendingChart({ data }) {
  if (!data?.length) return null

  const formatted = data.map(d => ({
    ...d,
    label: new Date(d.month + '-01').toLocaleString('default', { month: 'short' }),
  }))

  return (
    <div className="chart-wrap">
      <h3 className="section-title">Monthly Spending</h3>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={formatted} barSize={28}>
          <XAxis
            dataKey="label"
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 12, fill: 'var(--text-muted)' }}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 12, fill: 'var(--text-muted)' }}
            tickFormatter={(v) => `$${v}`}
          />
          <Tooltip
            formatter={(v) => [`$${v.toFixed(2)}`, 'Spend']}
            contentStyle={{
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              fontSize: '13px',
            }}
          />
          <Bar dataKey="total" radius={[4, 4, 0, 0]}>
            {formatted.map((_, i) => (
              <Cell
                key={i}
                fill={i === formatted.length - 1 ? 'var(--accent)' : 'var(--bar-muted)'}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
