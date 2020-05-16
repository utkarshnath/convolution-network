from torch.nn.parameter import Parameter
import torch
from torch.autograd import Function
from torch import tensor, nn
import math
import torch.nn.functional as F
import time

def test(a,b,cmp,cname=None):
    if cname is None: cname=cmp.__name__
    assert cmp(a,b),f"{cname}:\n{a}\n{b}"

def near(a,b): return torch.allclose(a, b, rtol=1e-3, atol=1e-5)
def test_near(a,b): test(a,b,near)

class conv2dFirstLayer(nn.Conv2d):
    def __init__(self,in_channels,out_channels,kernel_size,padding,stride,mask_layer,mask=1,parts=4,*kargs,**kwargs):
        super(conv2dFirstLayer, self).__init__(in_channels,out_channels,kernel_size,padding,stride,mask,*kargs, **kwargs)
        #self.mask = torch.ones(parts,out_channels,in_channels,kernel_size,kernel_size).cuda()
        #for i in range(1,parts):
        #    start = out_channels - i*out_channels//parts
        #    self.mask[i,start:out_channels] = 0
        self.padding = (padding,padding)
        self.stride = (stride,stride)
        self.mask_layer = mask_layer

    def forward(self,input):
        # print(self.mask[0].sum(),self.mask[1].sum(),self.mask[2].sum(),self.mask[3].sum())
        a = F.conv2d(input,self.weight,self.bias,self.stride,self.padding,self.dilation, self.groups)
        concatinatedTensor = torch.cat([a, a], dim=0)
        return concatinatedTensor

class conv2dFaster(nn.Conv2d):
    def __init__(self,in_channels,out_channels,kernel_size,padding,stride,mask_layer,mask=1,*kargs,**kwargs):
        super(conv2dFaster, self).__init__(in_channels,out_channels,kernel_size,padding,stride,mask,*kargs, **kwargs)
        #parts = 4
        #self.mask = torch.ones(parts,out_channels,in_channels,kernel_size,kernel_size).cuda()
        #self.parts = parts
        #for i in range(1,parts):
        #    start = out_channels - i*out_channels//parts
        #    self.mask[i,start:out_channels] = 0
        self.padding = (padding,padding)
        self.stride = (stride,stride)
        self.mask_layer = mask_layer
        self.out_channels = out_channels
        self.compression_factor = 4
        self.mask = 0
        #self.mask[out_channels//self.compression_factor:] = 0
        self.isFirst = True 

    def forward(self,input):
        l,_,_,_ = input.shape
        out = F.conv2d(input,self.weight,self.bias,self.stride,self.padding)
        
        if self.mask_layer:
           out[l//2:,self.out_channels//self.compression_factor:] = 0
        
        return out
        

class myconv2dFaster(nn.Conv2d):
    def __init__(self,in_channels,out_channels,kernel_size,padding,stride,mask_layer,conpression_factor=4,*kargs,**kwargs):
        super(myconv2dFaster, self).__init__(in_channels,out_channels,kernel_size,padding,stride,*kargs, **kwargs)
        self.out_channels = out_channels
        self.kernel_size = (kernel_size,kernel_size)
        self.padding = (padding,padding)
        self.stride = (stride,stride)
        self.mask_layer = mask_layer
        self.conpression_factor = conpression_factor
        self.mask = torch.ones(self.out_channels).cuda() 

    def forward(self,input):
        N,c,h,w = input.shape
        f = self.out_channels
        unfolded_input = torch._C._nn.im2col(input,self.kernel_size,(1,1),self.padding,self.stride)
        output_size = (h-self.kernel_size[0]+2*self.padding[0])//self.stride[0] + 1
        unfolded_input = unfolded_input.reshape(2,N//2,unfolded_input.shape[1],unfolded_input.shape[2])
        unfolded_weight = self.weight.view(self.out_channels,-1)
        out = (unfolded_weight) @ unfolded_input
        out = out.view(N,self.out_channels,output_size,output_size)
        # check masking
        if self.mask_layer:
           mask = torch.ones(N,self.out_channels,output_size,output_size).cuda() 
           mask[N//2:,self.out_channels//self.conpression_factor:] = 0
           out = out * mask
           return out
        return out
          
           
class batchNorm(nn.Module):
    def __init__(self,num_features,*kargs,**kwargs):
        super(batchNorm,self).__init__(*kargs,**kwargs)
        self.num_features = num_features
        self.bn1 = nn.BatchNorm2d(num_features)
        self.bn2 = nn.BatchNorm2d(num_features)

    def forward(self,input):
        l,_,_,_ = input.shape
        a = self.bn1(input[:l//2])
        d = self.bn2(input[l//2:])
        #d = F.batch_norm(input[l//2:], self.running_mean, self.running_var, self.weight, self.bias) 
        concatinatedTensor = torch.cat([a, d], dim=0)
        return concatinatedTensor

class linear(nn.Linear):
    def __init__(self,in_features, out_features, parts=4, bias=True,*kargs,**kwargs):
        super(linear, self).__init__(in_features, out_features, bias=True,*kargs, **kwargs)

    def forward(self,input):
        l,_ = input.shape
        a = F.linear(input[:l//2], self.weight, self.bias)
        d = F.linear(input[l//2:], self.weight, self.bias)
        concatinatedTensor = torch.cat([a, d], dim=0)
        return concatinatedTensor

class MyCrossEntropy(nn.Module):
    def __init__(self,alpha=1):
        super().__init__()
        self.alpha = alpha

    def forward(self, output, target):
        l,_ = output.shape
        #first = torch.cat([output[:l//8], output[2*l//8:3*l//8],output[4*l//8:5*l//8],output[6*l//8:7*l//8]], dim=0)
        #second = torch.cat([output[l//8:2*l//8], output[3*l//8:4*l//8],output[5*l//8:6*l//8],output[7*l//8:]], dim=0)
        
        log_preds1 = F.log_softmax(output[:l//2], dim=-1)
        nll1 = F.nll_loss(log_preds1, target)

        prob1 = F.softmax(output[:l//2], dim=-1)
        prob2 = F.softmax(output[l//2:], dim=-1)

        kl = (prob1 * torch.log(1e-6 + prob1/(prob2+1e-6))).sum(1)

        return nll1 + self.alpha * kl.mean()

class Identity(nn.Module):
    def __init__(self,alpha=1):
        super().__init__()
        self.alpha = alpha

    def forward(self, output, target):
        return output[0]
