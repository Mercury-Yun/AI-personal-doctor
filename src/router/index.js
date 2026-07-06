import { createRouter, createWebHistory } from 'vue-router'
import { isMobileView, MOBILE_HIDDEN_ROUTES } from '../utils/mobileView'
import Dashboard from '../views/Dashboard.vue'
import FamilyHome from '../views/FamilyHome.vue'
import FamilyProfiles from '../views/FamilyProfiles.vue'
import FamilyMedications from '../views/FamilyMedications.vue'
import FamilyRecords from '../views/FamilyRecords.vue'
import DoctorChat from '../views/DoctorChat.vue'
import HealthProfile from '../views/HealthProfile.vue'
import MedicationManager from '../views/MedicationManager.vue'
import Reminder from '../views/Reminder.vue'
import DeviceStatus from '../views/DeviceStatus.vue'
import PhotoMedicine from '../views/PhotoMedicine.vue'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'Dashboard', component: Dashboard, meta: { title: '健康总览' } },
  { path: '/family', name: 'FamilyHome', component: FamilyHome, meta: { title: '家属守护' } },
  { path: '/family/profiles', name: 'FamilyProfiles', component: FamilyProfiles, meta: { title: '健康档案' } },
  { path: '/family/medications', name: 'FamilyMedications', component: FamilyMedications, meta: { title: '提醒管理' } },
  { path: '/family/records', name: 'FamilyRecords', component: FamilyRecords, meta: { title: '病例管理' } },
  { path: '/doctor-chat', name: 'DoctorChat', component: DoctorChat, meta: { title: 'AI医生' } },
  { path: '/photo-medicine', name: 'PhotoMedicine', component: PhotoMedicine, meta: { title: '拍照问药' } },
  { path: '/profiles', name: 'HealthProfile', component: HealthProfile, meta: { title: '健康档案' } },
  { path: '/medications', name: 'MedicationManager', component: MedicationManager, meta: { title: '药物管理' } },
  { path: '/reminders', name: 'Reminder', component: Reminder, meta: { title: '用药提醒' } },
  { path: '/device', name: 'DeviceStatus', component: DeviceStatus, meta: { title: '设备与语音' } }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  if (!isMobileView()) {
    // 看板（横屏）不使用家属端页面，回退到桌面版
    if (to.path === '/family') return '/dashboard'
    if (to.path === '/family/profiles') return '/profiles'
    if (to.path === '/family/medications') return '/medications'
    if (to.path === '/family/records') return '/dashboard'
    return true
  }
  // 手机窄屏使用家属端页面
  if (to.path === '/dashboard') return '/family'
  if (to.path === '/profiles') return '/family/profiles'
  if (to.path === '/medications' || to.path === '/reminders') return '/family/medications'
  if (to.path === '/records') return '/family/records'
  if (MOBILE_HIDDEN_ROUTES.has(to.path)) {
    return '/family'
  }
  return true
})

export default router
