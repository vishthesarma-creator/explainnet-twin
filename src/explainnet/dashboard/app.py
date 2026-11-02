"""One shared four-page shell; legacy URLs redirect through this bootstrap."""
import streamlit as st
from pydantic import ValidationError

from explainnet.dashboard.client import ClientSettings
from explainnet.dashboard.four_pages import PAGES
from explainnet.dashboard.theme import CSS

st.set_page_config(page_title='ExplainNet Twin',page_icon='◉',layout='wide',initial_sidebar_state='expanded')
st.html(CSS)
st.sidebar.markdown('<div class="brand">ExplainNet Twin</div>',unsafe_allow_html=True)
st.sidebar.caption('Observe · Explain · Verify')
try:settings=ClientSettings.environment()
except ValidationError:
    st.sidebar.button('Refresh now',on_click=st.rerun)
    st.sidebar.toggle('Auto-refresh every 10 seconds',key='refresh_active_view')
    st.error('Invalid API identity. Relaunch the selected application profile.');st.stop()
names=['live','diagnosis','twin_recovery','results']
pages=[st.Page('page_routes/'+name+'.py',title=title,url_path=url,default=i==0)
    for i,(name,title,url) in enumerate(zip(names,PAGES,['','diagnosis','twin-recovery','results'],strict=True))]
legacy=[st.Page('page_routes/'+name+'.py',title='Legacy '+name,url_path=name)
    for name in ['overview','network','incidents','twin','recovery','evidence']]
page=st.navigation(pages+legacy,position='hidden')
for name,title in zip(names,PAGES,strict=True):st.sidebar.page_link('page_routes/'+name+'.py',label=title)
st.sidebar.toggle('Auto-refresh every 10 seconds',value=False,key='refresh_active_view')
if st.sidebar.button('Refresh now'):st.rerun()
st.session_state['_shell_status_slot']=st.sidebar.empty()
with st.sidebar.expander('Switch application profile'):
    st.link_button('Trained application','http://127.0.0.1:8501')
    st.link_button('Observed-only laboratory','http://127.0.0.1:8502')
    st.caption('Each profile has a separate backend/store. Switching performs no laboratory operation.')
page.run()
