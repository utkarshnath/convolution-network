from helper import *
from run import Runner, Learn
from IPython.core.debugger import set_trace
from torch import tensor, nn, optim
from callback import *
import torch
import torch.nn.functional as F
from mask import randomShape,swastik,star,circle,oval,firstLayerMasking,secondLayerMasking,thirdLayerMasking
from torch.nn.parameter import Parameter
# from .. import init
from torch.autograd import gradcheck
from schedulers import combine_schedules, sched_cos
from myconv import myconv2d
from model import xresnet18,xresnet50,xresnet101
from modelFaster import xresnet_fast18,xresnet_fast50,xresnet_fast101 
import time
from convFaster import *
#from optimizers import *

def load_model(model, state_dict_file_path=None):
    if state_dict_file_path is not None:
        model.load_state_dict(torch.load(state_dict_file_path))
    return model

def imagenet_resize(x): return x.view(-1, 3, 224, 224)

if __name__ == "__main__":
   start = time.time()
   device = torch.device('cuda',0)
   torch.cuda.set_device(device)
   #device = 'cuda' if torch.cuda.is_available() else 'cpu'
   #n_gpu = torch.cuda.device_count()
   batch_size = 32
   image_size = 224
   c = 1000
   train = True
   data = load_data(batch_size, image_size,0)
   lr_finder = False
   is_individual_training = False
   last_epoch_done_idx = None


   lr = 0.8
   lr_sched = combine_schedules([0.1, 0.9], [sched_cos(lr/10., lr), sched_cos(lr, lr/1e5)])
   lr_scheduler = ParamScheduler('lr', lr_sched)
   cbfs = [lr_scheduler,CudaCallback()]


   #lr = 1e-3
   #lr_sched = combine_schedules([0.1, 0.9], [sched_cos(lr/10., lr), sched_cos(lr, lr/1e5)])
   #beta1_sched = combine_schedules([0.1, 0.9], [sched_cos(0.95, 0.85), sched_cos(0.85, 0.95)])
   #lr_scheduler = ParamScheduler('lr', lr_sched)
   #beta1_scheduler = ParamScheduler('beta1', beta1_sched)
   #cbfs = [lr_scheduler,beta1_scheduler,CudaCallback()]
 
   if is_individual_training:
      epoch = 60
      compression_factor = 1
      loss_func = F.cross_entropy
      cbfs+=[SaveModelCallback("individual-50-original(adam)"),AvgStatsCallback(metrics=[accuracy,top_k_accuracy])]
      model = xresnet50(c_out=c,resize=imagenet_resize,compression_factor=compression_factor)
   else:
      # currently need to set compression rate manually in convFaster.py
      epoch = 80
      loss_func = MyCrossEntropy(1)
      cbfs+=[SaveModelCallback("combined-50-16"),AvgStatsCallback()]
      model = xresnet_fast50(c_out=c,resize=imagenet_resize)
      if last_epoch_done_idx is not None: model = load_model(model, state_dict_file_path="/scratch/un270/combined-50-4/{}.pt".format(last_epoch_done_idx)) 

   #model = nn.DataParallel(model)
   #model = model.to(device)

   end = time.time()
   print("Loaded model", end-start)
   
   
   opt = optim.SGD(model.parameters(),lr)
   #opt = StatefulOptimizer(model.parameters(), [weight_decay, adam_step],
   #     stats=[AverageGrad(), AverageSqGrad(), StepCount()], lr=0.001, wd=1e-2, beta1=0.9, beta2=0.99, eps=1e-6)
   learn = Learn(model,opt,loss_func, data)
   
   if lr_finder:
      cbfs = [CudaCallback(),LR_find(),Recorder()]

   run = Runner(learn,cbs = cbfs)
   run.fit(epoch, start_epoch = 0 if last_epoch_done_idx is None else last_epoch_done_idx+1)  

#if lr_finder:
#   print(cbfs[-1].lrs)
#   print(cbfs[-1].losses)
