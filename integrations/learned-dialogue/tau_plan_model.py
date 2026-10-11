"""Masked group-balanced linear source-planning head; fresh CPU parameters."""
import numpy as np


def sigmoid(z):return 1/(1+np.exp(-np.clip(z,-80,80)))


def loss_gradient(w,b,x,y,m,gw,q,den):
    z=x@w+b;p=sigmoid(z);n=w.size
    scale=m*gw[:,None]/np.maximum(den,1e-12)[None,:];active=den>0;scale[:,~active]=0;scale/=max(1,int(active.sum()))
    bce=(1-y)*np.logaddexp(0,z)+y*q*np.logaddexp(0,-z)
    dz=(p-y)*np.where(y>.5,q,1)*scale
    gradient=x.T@dz;gb=dz.sum(0);data=float((bce*scale).sum());reg=.005*float((w.astype(np.float64)**2).sum())/n
    norm=float(np.linalg.norm(gradient));gradient+=.01*w/n
    if not np.isfinite(gradient).all() or not np.isfinite(gb).all():raise ValueError('Nonfinite gradient')
    return data+reg,gradient,gb,{'data_BCE':data,'mean_parameter_L2':reg,'data_weight_gradient_norm':norm}


def metrics(z,y,m,labels,threshold=None):
    if threshold is None:threshold=np.full(len(labels),.5)
    prob=sigmoid(z);pred=prob>=threshold;known=m.astype(bool);positive=y>.5;per={};total=np.zeros(3,int);f1=[]
    for j,label in enumerate(labels):
        tp=int((pred[:,j]&positive[:,j]&known[:,j]).sum());fp=int((pred[:,j]&~positive[:,j]&known[:,j]).sum());fn=int((~pred[:,j]&positive[:,j]&known[:,j]).sum());n=int(known[:,j].sum())
        value=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0
        if n:f1.append(value)
        per[label]={'known':n,'unknown':len(y)-n,'positive':int((positive[:,j]&known[:,j]).sum()),'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,'F1':value}
        total+=[tp,fp,fn]
    tp,fp,fn=map(int,total)
    return {'rows':len(y),'known_elements':int(m.sum()),'unknown_elements':int((1-m).sum()),'micro_F1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,'macro_F1':float(np.mean(f1)) if f1 else None,'micro_precision':tp/(tp+fp) if tp+fp else None,'micro_recall':tp/(tp+fn) if tp+fn else None,'per_class':per,'bank_authority':False,'financial_masks':'UNKNOWN','qualified':False}
