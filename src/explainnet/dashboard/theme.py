"""Shared accessible dark presentation; data and status text remain explicit."""
CSS='''<style>
.stApp {background:#0F141C;color:#E8EDF4} [data-testid="stSidebar"] {background:#151F2E;border-right:1px solid #304056}
h1,h2,h3,h4 {color:#E8EDF4;letter-spacing:-.025em} h1 {font-size:2.25rem!important;font-weight:750}
.block-container {max-width:1440px;padding:2.4rem 2rem 3rem} .stCaption {color:#ACBBD0}
.status-card {background:#151F2E;border:1px solid #304056;border-top:2px solid #37B5AD;border-radius:10px;padding:16px;margin:6px 0 14px;min-height:100px}
.status-card span {display:block;color:#ACBBD0;font-size:.82rem;margin-bottom:10px} .status-card strong {color:#E8EDF4;font-size:1.1rem}
[data-testid="stVerticalBlockBorderWrapper"] {background:#151F2E;border-radius:10px}
button {border-radius:7px!important} button:focus-visible,a:focus-visible,input:focus-visible {outline:3px solid #37B5AD!important;outline-offset:3px}
a {color:#65D7CF} .brand {font-weight:800;font-size:1.5rem;color:#E8EDF4}.eyebrow {color:#65D7CF;font-size:.8rem;letter-spacing:.1em}
@media(max-width:900px){.block-container{padding:1.4rem 1rem} h1{font-size:1.8rem!important}}
</style>'''


def plot_theme(figure):
    figure.update_layout(template='plotly_dark',paper_bgcolor='#151F2E',plot_bgcolor='#151F2E',
        font={'color':'#E8EDF4'},colorway=['#37B5AD','#8DABDF','#DAB968','#E88E8E'],
        hoverlabel={'bgcolor':'#24354B','font_color':'#E8EDF4'},legend={'font':{'color':'#E8EDF4'}})
    return figure
